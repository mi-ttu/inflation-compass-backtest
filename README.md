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
**Mon-Fri at 2:30 PM Central** (30 min before the NYSE close, matching the
MaxAlpha backtest project's schedule), via `backtest/run_refresh.ps1` (a
thin wrapper around `run_daily.py` that logs full output, UTF-8, to
`backtest/refresh_logs/`, keeping the 20 most recent runs). It's configured
to catch up automatically if the machine was off or asleep at the scheduled
time (`StartWhenAvailable`), and runs under the logged-in user account, so
no credentials are stored.

The task fires every weekday, but `run_daily.py` checks the NYSE
`trading_calendar` itself and no-ops on weekday holidays (Thanksgiving,
Christmas, ...) that a plain Mon-Fri trigger can't skip on its own — see
`is_trading_day()` in that file.

Because the run happens before the close, "latest data" means the most
recently *finalized* session's close — yfinance returns a partial,
still-in-progress bar for the current session until it actually settles,
and `load_bronze_to_silver.py` filters that incomplete row out rather than
let it violate the database's NOT NULL constraint.

(The standalone-install path below sets up an equivalent task
automatically — see that section instead if you used `install.ps1`.)

This task is local to each machine — set up separately from `bootstrap.py`
above, it isn't part of the git-tracked project state. To recreate it on
another machine:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "<repo path>\backtest\run_refresh.ps1"' `
  -WorkingDirectory "<repo path>"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 2:30PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "InflationCompassChartRefresh" -Action $action `
  -Trigger $trigger -Settings $settings -RunLevel Limited `
  -Description "Inflation Compass backtest: refresh + daily status email, trading days at 2:30 PM"
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
at Today's Close**. The recommendation is a live preview
(`backtest/live_preview.py`): the regime signal recomputed with delayed
intraday quotes for ^GSPC and the seven sector ETFs spliced in as today's
row (T5YIE isn't live — FRED lags — so its latest published value is
carried forward). It's flagged "not final" while the session is open, and
the email calls out a **CHANGE** when the two cards differ. Sent as rich
HTML with a plain-text fallback.

Both emails also carry a **decision matrix** - every combination of the four
signals (Growth, Level, Momentum, Sector) with the resulting inflation state,
regime and allocation, and the row you're currently in highlighted. It is
generated from the same `decide()` the signal uses, so it can't drift from it.

Both emails (the 2:30 PM status and the 3:15 PM alert) also embed four
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

## 3:15 PM final-close check

The 2:30 PM run decides on delayed intraday quotes that can still move before
the close. A second scheduled task, `InflationCompassFinalCheck` (Mon-Fri
3:15 PM Central = 4:15 PM Eastern, 15 minutes after the close), reruns the
signal on the day's real closing prices (`backtest/run_final_check.py`) and
**emails only if the recommended allocation differs from the one the 2:30 PM
run saved** (`data/last_status.json`, local state). If it matches, nothing is
sent and the log says so. The alert shows both allocations, which signals
flipped (growth / inflation) and how the S&P 500 moved between the two runs.
If no 2:30 PM baseline exists for the day (that run failed or didn't happen)
it sends the final allocation anyway, flagged as such.

Yahoo's daily bars can lag the close by a few minutes, so before refreshing it
polls ^GSPC and the seven sector ETFs once a minute until all are dated today
and unchanged across two polls, for up to 15 minutes. If they never settle it
runs on what it has and the email says the closing prices may still move. It
refuses to run before 4 PM Eastern. Its output goes to
`backtest/refresh_logs/final_*.log`. The same dashboard refresh runs at 3:15,
so the dashboard ends the day on final closes.

The 5-year breakeven (T5YIE) is published by FRED with a lag, so the final-close
check still uses its latest published value, same as the 2:30 PM run.

To recreate the task on another machine, register `run_refresh.ps1` with
`-TaskScript run_final_check.py -LogPrefix final` on a Mon-Fri 3:15 PM trigger
(see `installer/install.ps1` for the standalone install's equivalent).

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
4. Registers a **Mon-Fri, 2:30 PM** Windows Scheduled Task (current-user
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
