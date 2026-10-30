# Inflation Compass Backtest

An independent backtest of David Varadi's ["Inflation Compass Model"](https://cssanalytics.wordpress.com/2026/07/27/the-inflation-compass-model/)
(cssanalytics, 2026-07-27) — a tactical sector-rotation strategy that holds
one of four sector/bond positions based on a growth signal (SPY vs. 200-day
SMA) and an inflation signal (T5YIE vs. 2% Fed target).

Built with a DuckDB bronze/silver/gold pipeline: raw vendor pulls on disk
(bronze) → curated, calendar-aligned tables in `data/curated.duckdb`
(silver) → derived regime signals and backtest returns (gold).

## What's here

- `ingest/` — pulls raw data: yfinance (equities/ETFs), FRED (rates,
  inflation expectations, CPI), Ken French's Data Library (industry
  portfolios, used only to extend sector returns before 1998).
- `transform/` — builds the NYSE trading calendar, reconciles total-return
  series from raw price + dividends, aligns FRED series onto the trading
  calendar, and runs the regime signal engine.
- `backtest/` — the strategy variants (original 2003+, Enhanced, Extended
  1990+, several levered and instrument-substitution variants) plus
  `interactive_chart.html`, the published chart/dashboard, and the two
  scripts below that build and refresh it.

`data/curated.duckdb` and `data/raw/` are git-ignored — the database is
regenerated locally, not committed (see **First-time setup**).

## First-time setup (new machine, or after cloning)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python.exe backtest/bootstrap.py
```

`bootstrap.py` initializes the database schema, builds the NYSE trading
calendar, pulls the Fama-French industry data (a one-time, essentially
static pull), then hands off to `refresh_chart.py` for the full historical
data pull, the regime signal engine, the three backtest variants the chart
displays, and an up-to-date `interactive_chart.html`. It refuses to run if
`data/curated.duckdb` already exists, to avoid silently clobbering it.

This does a full historical pull across ~36 years of daily data — expect it
to take a few minutes.

## Ongoing refresh

```bash
.venv/Scripts/python.exe backtest/refresh_chart.py
```

Re-pulls the latest yfinance/FRED data, reruns the transform and signal
pipeline, regenerates the five backtest variants the chart uses (Levered
TQQQ/ERX monthly and daily-signal, Unlevered QQQ monthly, Hybrid QLD/XLE
monthly and daily-signal), and patches the fresh data — including the
current-allocation banner and the daily calendar table — into
`backtest/interactive_chart.html` in place.

The underlying data only updates once per trading day, so running this more
than daily is wasted effort — but daily *is* the right default now that the
dashboard includes daily-signal variants (checked every trading day, not
just month-end): a stale banner or calendar table could show yesterday's
allocation as still current when it's actually changed. See the Task
Scheduler setup below.

Note `refresh_chart.py` on its own doesn't gate on the trading calendar or
send email — use `backtest/run_daily.py` for that (see below); it's what
the scheduled task and `install.ps1` actually call.

## Viewing the chart

`interactive_chart.html` is fully self-contained — every number is embedded
directly in the file, nothing is fetched at load time except Google Fonts.
Open it directly in a browser (`file:///.../backtest/interactive_chart.html`)
and bookmark that URL — no local server needed. Reloading the page re-reads
the file from disk, so it picks up whatever `refresh_chart.py` last wrote.

It's also published as a Claude Artifact for easier sharing; the URL is in
`backtest/ARTIFACT_URL.txt`. Publishing an update there still requires a
Claude Code session (the Artifact tool isn't callable from a bare script).

## Keeping it current automatically

A Windows Scheduled Task named `InflationCompassChartRefresh` runs
**Mon-Fri at 3:05 PM Central** (4:05 PM Eastern, 5 minutes after the NYSE
close, matching the MaxAlpha backtest project's schedule), via `backtest/run_refresh.ps1` (a
thin wrapper around `run_daily.py` that logs full output, UTF-8, to
`backtest/refresh_logs/`, keeping the 20 most recent runs). It's configured
to catch up automatically if the machine was off or asleep at the scheduled
time (`StartWhenAvailable`), and runs under the logged-in user account, so
no credentials are stored.

The task fires every weekday, but `run_daily.py` checks the NYSE
`trading_calendar` itself and no-ops on weekday holidays (Thanksgiving,
Christmas, ...) that a plain Mon-Fri trigger can't skip on its own — see
`is_trading_day()` in that file.

The run happens after the close so the day's data and the email are on **final
closing prices**. Yahoo's daily bars can still move for a few minutes after 4 PM,
so `run_daily.py` first waits for them to settle (`backtest/close_data.py`):
nothing counts as final before 4:05 PM Eastern, and ^GSPC plus the seven sector
ETFs must read the same on two polls a minute apart, for up to 15 minutes. If
they never settle it carries on with what it has and the email says the closing
prices may still move. (Until 2026-10-29 the run was at 2:30 PM on a live
intraday preview, with a separate 3:15 PM final-close check; see below.) Run by
hand during the session, it still works and reports a live preview; a partial,
still-in-progress bar for the current session is filtered out by
`load_bronze_to_silver.py` rather than violating the NOT NULL constraint.

(The standalone-install path below sets up an equivalent task
automatically — see that section instead if you used `install.ps1`.)

This task is local to each machine — set up separately from `bootstrap.py`
above, it isn't part of the git-tracked project state. To recreate it on
another machine:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "<repo path>\backtest\run_refresh.ps1"' `
  -WorkingDirectory "<repo path>"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 3:05PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "InflationCompassChartRefresh" -Action $action `
  -Trigger $trigger -Settings $settings -RunLevel Limited `
  -Description "Inflation Compass backtest: after-close refresh + daily status email, trading days at 3:05 PM Central"
```

Note that this only regenerates the local HTML file — pushing the refreshed
data to the published Artifact URL still requires a Claude Code session,
since the Artifact tool isn't callable from a bare script.

## Daily status email

`run_daily.py` (what the scheduled task above actually calls, and what
`install.ps1` registers too) sends a status email **every trading day it
runs** — via `backtest/notify.py`, laid out like the MaxAlpha backtest
project's status email — with two cards for the Hybrid (QLD/XLE), Daily
variant: **Currently Held** (decided at the prior close) and **Recommended
at Today's Close**. At the scheduled 3:05 PM run the recommendation is final:
it is decided on today's closing prices (`backtest/live_preview.py`). If the
script is run during the session it becomes a live preview instead (delayed
intraday quotes for ^GSPC and the seven sector ETFs spliced in as today's row)
and is flagged "not final". The email calls out a **CHANGE** when the two cards
differ. Sent as rich
HTML with a plain-text fallback.

The allocation both emails recommend uses the **2-day regime confirmation rule**
(the same rule as the dashboard's "Hybrid, Daily, 2-day confirm" series, reused from
`simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal_confirm2.py`): the holding
changes only after the same new regime shows on two consecutive closes, which removes
the 1-2 day flips around a threshold (about 4.5 a year in the plain daily rules; the
backtest drops holdings of 2 days or less to about 1 a year at the same CAGR). When
today's raw signal disagrees with the confirmed allocation, the email says so ("pending
confirmation") and the decision matrix's NOW row shows the raw signal. This is a
tested variant, not part of Varadi's published rules. The dashboard's
"Current Recommended Allocation" banner follows the same confirmed signal on the Original
view and labels it "2-day confirmed" (the Enhanced view has no confirmed variant, so its
banner is labelled "unconfirmed"); the plain "Hybrid, Daily" chart series stays the
unconfirmed daily signal, alongside its "2-day confirm" counterpart.

If FRED (the 5-year breakeven source) is down or delayed, both emails show a red **stale data
warning** at the top: the breakeven's last publication date, how many trading sessions ago that
was, and which signals are affected (Inflation level and momentum; Growth and Sector use live
market data). It triggers when the latest reading is 2 or more sessions old (FRED normally runs
one session behind). The 5-year breakeven comes from the **U.S. Treasury first** (the 5-year nominal par yield minus the
5-year real/TIPS par yield, which is exactly how FRED builds `T5YIE`; the two agree to the cent), with
FRED as the fallback and the previous good pull behind that. Treasury is the origin of the data and
FRED a repackaging of it. `ingest/fetch_fred.py` refuses Treasury data that disagrees with the
previous pull (so a silent format change can't corrupt the signal), and a response that isn't a real
CSV is never saved (FRED serves an HTML maintenance page with HTTP 200), so an outage at either
source no longer breaks the daily run. The stored series records its provider (`TREASURY` / `FRED`).

The dashboard's **Signal status** panel (Original view, under the allocation banner) shows the same
four signal charts, the decision matrix with today's row highlighted, and the pending / stale notices,
drawn as native SVG so they follow the light/dark theme. Its data (`SIGNAL_STATUS`) is patched in by
`run_daily.py` and `run_final_check.py` right after they build the preview (`refresh_chart.patch_signal_status`),
so a manual `refresh_chart.py` run alone leaves it as it was.

Both emails also carry a **decision matrix** - every combination of the four
signals (Growth, Level, Momentum, Sector) with the resulting inflation state,
regime and allocation, and the row you're currently in highlighted. It is
generated from the same `decide()` the signal uses, so it can't drift from it.

Both emails (the daily status and the optional final-close alert) also embed four
**signal charts** as inline images, in the style of the MaxAlpha project's
emails: the last ~3 months of each input against its threshold, with the
background shaded by the holding decided that day, and a True/False badge -
Growth (S&P 500 vs its 200-day average), Inflation level (5y breakeven vs
2.0%), Inflation momentum (breakeven vs 60 trading days earlier) and Sector
momentum (cyclicals/defensives 60-day trend). Rendered with matplotlib
(`backtest/signal_charts.py`); if matplotlib is unavailable the email is
sent without them.

It's opt-in and fails safe: if `backtest/email_config.json` doesn't exist
or is incomplete, notification is silently skipped with a printed note —
the data refresh itself never fails just because email isn't set up. To
enable it:

1. Generate a Gmail **App Password** (Google Account → Security → 2-Step
   Verification → App passwords) — a revocable, mail-only credential,
   not your real account password.
2. Copy `backtest/email_config.example.json` to `backtest/email_config.json`
   and fill in your Gmail address, the app password, and where you want
   the alert sent. This file is git-ignored — it never gets committed.

## Optional final-close check (not scheduled)

From 2026-10-08 to 2026-10-29 the daily run was at 2:30 PM on a live intraday
preview, and a second task, `InflationCompassFinalCheck` (3:15 PM Central), reran
the signal on the day's closing prices (`backtest/run_final_check.py`) and emailed
**only if the recommended allocation differed** from the one the earlier run saved
(`data/last_status.json`, local state). Now that the daily run itself happens after
the close, that check is redundant: the task is disabled (the installer disables it
on older installs rather than deleting it), and the script stays in the repo for
anyone who goes back to an intraday run. It uses the same wait-for-settled-closes
logic (`backtest/close_data.py`), and its output goes to
`backtest/refresh_logs/final_*.log`. To re-enable it, register `run_refresh.ps1`
with `-TaskScript run_final_check.py -LogPrefix final` on a Mon-Fri trigger after
the close, and move the daily run back before the close.

## Standalone install (no Python required)

For a machine you don't want to set up a dev environment on: no Python, no
git clone, no venv, just a couple of double-clicks.

**Easiest path** — download the pre-built package from
[GitHub Releases](https://github.com/mi-ttu/inflation-compass-backtest/releases/latest),
extract the zip, and run:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

**To rebuild it yourself** (e.g. after a code change, before cutting a new
release):

```powershell
powershell -ExecutionPolicy Bypass -File installer\build_release.ps1
```

produces `dist\InflationCompassRelease\` (and a zip of the same), containing
`install.ps1` plus a clean copy of the app source — `backtest/email_config.json`
(a real credential, if you've set one up) is deliberately excluded; only
the `.example` template ships. Publish a new release with:

```powershell
gh release create vX.Y.Z dist\InflationCompassRelease.zip --title "..." --notes "..."
```

This installs everything into `%LOCALAPPDATA%\InflationCompass\` (no admin
rights needed):

1. Downloads a self-contained "embeddable" Python runtime (the official
   distribution from python.org) into `python-runtime\` -- this app never
   touches or depends on any Python already on the machine, and vice versa.
2. Installs the app's dependencies into that isolated runtime.
3. Runs the app once immediately: first-time database bootstrap (pulls
   ~36 years of public data, a few minutes) so there's something to see
   right away.
4. Registers a **Mon-Fri, 3:05 PM** (after the close) Windows Scheduled Task (current-user
   scope, no stored credentials, `StartWhenAvailable` so it catches up if
   the machine was off) so the dashboard always reflects data through the
   most recent trading day, with no manual steps.
5. Drops a desktop shortcut straight to the dashboard.

Re-running `install.ps1` later (e.g. after pulling a code update and
rebuilding the release) is safe — it refreshes the app source and
re-registers the task, but never touches an already-bootstrapped database.

The email-on-allocation-change feature (see above) comes along for free
since it's just part of `backtest/`, but stays off until you manually drop
a filled-in `email_config.json` into `<install dir>\app\backtest\` — the
installer doesn't prompt for credentials or set this up automatically.

One thing to expect: since the installer isn't code-signed, Windows
SmartScreen may flag it as coming from an unrecognized publisher on first
run — "More info" → "Run anyway" gets past it.

Note the embeddable runtime's `._pth` file runs Python in an isolated path
mode where neither `PYTHONPATH` nor the usual "add the running script's own
directory to `sys.path`" behavior apply — `install.ps1` appends an explicit
`..\app\backtest` entry to it, since that's the only directory whose
scripts import each other as siblings (e.g. `from _levered_common import
...`). If a future script anywhere else in the app starts doing the same,
it'll need the same treatment.

## Reproducing on another machine

Each machine is an independent replica, not a synced copy: clone the repo,
run `bootstrap.py` once, and it pulls the same public data (yfinance, FRED,
Ken French) that this machine did, converging to the same database and
backtest results without needing to copy `curated.duckdb` around.

## Caveats

The pre-2003 segment splices in a Cleveland Fed model estimate (EXPINF5YR)
and Fama-French industry proxies in place of real T5YIE/SPDR data; the
pre-2010 levered segments use synthetic daily-compounded leverage with no
fund fees or financing cost; none of this reflects real trading costs,
taxes, or slippage. Not investment advice.

## Robustness tests

`robustness/` stress-tests the Hybrid QLD/XLE daily variant beyond its own
backtest:

```
.venv/Scripts/python.exe robustness/run_tests.py      # ~6s, writes robustness/results.json
.venv/Scripts/python.exe robustness/build_report.py   # writes robustness/report.html
```

1. Out of sample (1990-2002, before the published 2003+ backtest), other
   goldilocks holdings (QQQ/SPY/XLK), and all 24 regime-to-holding
   assignments
2. Parameter robustness: one-at-a-time sweeps plus 300 random joint nudges
3. Execution stress: costs, a day of delay, inflation data 1-2 days late, a
   costed pre-2006 QLD stand-in, and the live 2:30 PM CT decision from
   60-minute bars
4. Walk-forward re-selection of settings each year from past data only
5. Block-bootstrap synthetic histories (2002 on)
6. A two-day confirmation rule (`confirm_test.py`, `confirm_regime_test.py`):
   requiring the whole regime to hold two closes before switching cuts
   trading from ~11 to ~7 times a year and helps once trading costs are
   included; requiring only the inflation signal to hold barely helps

`robustness/engine.py` reproduces the backtest exactly with the published
settings (checked by `engine.validate()`). The report shares its styling
with `../max-alpha-backtest/robustness/report_template.html`. The prose
findings in `build_report.py` were written for the 2026-09-30 run; reread
them after rerunning. Published at
https://claude.ai/artifact/Je2EKmP8snc3RwUKPg6cS7.
