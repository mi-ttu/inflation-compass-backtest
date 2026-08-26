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
pipeline, regenerates the three backtest variants the chart uses (Levered
TQQQ/ERX monthly, Levered TQQQ/ERX daily-signal, Unlevered QQQ monthly), and
patches the fresh data into `backtest/interactive_chart.html` in place.

The underlying data only updates once per trading day (after market close),
so running this more than daily is wasted effort. A weekly cadence is
plenty for a monthly-rebalancing strategy — see the Task Scheduler setup
below.

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

A Windows Scheduled Task named `InflationCompassChartRefresh` runs every
Sunday at 8:00 PM local time, via `backtest/run_refresh.ps1` (a thin
wrapper around `refresh_chart.py` that logs full output, UTF-8, to
`backtest/refresh_logs/`, keeping the 20 most recent runs). It's configured
to catch up automatically if the machine was off or asleep at the scheduled
time (`StartWhenAvailable`), and runs under the logged-in user account, so
no credentials are stored.

This task is local to each machine — set up separately on `bootstrap.py`
above, it isn't part of the git-tracked project state. To recreate it on
another machine:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "<repo path>\backtest\run_refresh.ps1"' `
  -WorkingDirectory "<repo path>"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 8:00PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "InflationCompassChartRefresh" -Action $action `
  -Trigger $trigger -Settings $settings -RunLevel Limited `
  -Description "Weekly refresh of the Inflation Compass backtest chart"
```

Note that this only regenerates the local HTML file — pushing the refreshed
data to the published Artifact URL still requires a Claude Code session,
since the Artifact tool isn't callable from a bare script.

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
