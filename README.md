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

The underlying data only updates once per trading day (after market
close), so running this more than daily is wasted effort — but daily
*is* the right default now that the dashboard includes daily-signal
variants (checked every trading day, not just month-end): a stale banner
or calendar table could show yesterday's allocation as still current when
it's actually changed. See the Task Scheduler setup below.

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
**daily at 6:00 AM** local time, via `backtest/run_refresh.ps1` (a thin
wrapper around `refresh_chart.py` that logs full output, UTF-8, to
`backtest/refresh_logs/`, keeping the 20 most recent runs). It's configured
to catch up automatically if the machine was off or asleep at the scheduled
time (`StartWhenAvailable`), and runs under the logged-in user account, so
no credentials are stored.

(The standalone-install path below sets up an equivalent daily task
automatically — see that section instead if you used `install.ps1`.)

This task is local to each machine — set up separately from `bootstrap.py`
above, it isn't part of the git-tracked project state. To recreate it on
another machine:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "<repo path>\backtest\run_refresh.ps1"' `
  -WorkingDirectory "<repo path>"
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "InflationCompassChartRefresh" -Action $action `
  -Trigger $trigger -Settings $settings -RunLevel Limited `
  -Description "Daily refresh of the Inflation Compass backtest chart"
```

Note that this only regenerates the local HTML file — pushing the refreshed
data to the published Artifact URL still requires a Claude Code session,
since the Artifact tool isn't callable from a bare script.

## Email alert on allocation change

`run_daily.py` (what the scheduled task above actually calls, and what
`install.ps1` registers too) checks after every refresh whether the Hybrid
(QLD/XLE), Daily variant's current holding differs from the last run's —
i.e. whether the regime actually switched — and emails **only** when it
has, via `backtest/notify.py`.

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

`data/last_allocation.json` tracks the last-seen holding (also git-ignored,
regenerated locally). The very first run after enabling this just records
the current holding without emailing, since there's nothing yet to compare
it against — you'll get an email starting from the next actual regime
change.

## Standalone install (no Python required)

For a machine you don't want to set up a dev environment on, `installer/`
builds a self-contained package that installs the dashboard with a couple
of double-clicks -- no Python, no git clone, no venv.

```powershell
powershell -ExecutionPolicy Bypass -File installer\build_release.ps1
```

produces `dist\InflationCompassRelease\` (and a zip of the same), containing
`install.ps1` plus a clean copy of the app source. Hand that folder or zip
to the target machine and run:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
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
4. Registers a **daily** Windows Scheduled Task (current-user scope, no
   stored credentials, `StartWhenAvailable` so it catches up if the
   machine was off) so the dashboard always reflects data through the
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
