"""Single entry point for the scheduled task (and the standalone installed
app): bootstraps the database from scratch if it doesn't exist yet
(first run after install), otherwise just does the normal incremental
refresh. Either way, ends with an up-to-date interactive_chart.html, then
sends a daily status email reporting the Hybrid (QLD/XLE), Daily variant's
current allocation and the allocation decided at today's close (see
live_preview.py) -- every trading day this runs, not just on a change
(see notify.py -- silently skipped if email isn't configured).

Scheduled Mon-Fri at 3:05 PM Central (4:05 PM ET), 5 minutes after the
close, same as the MaxAlpha backtest project, so the email carries the
definitive allocation from final closing prices: it first waits for Yahoo's
closing bars to settle (close_data.py). Until 2026-10-29 it ran at 2:30 PM on
a live intraday preview, followed by a 3:15 PM final-close check
(run_final_check.py), which is now redundant and no longer scheduled. Run
before the close (e.g. manually), it still works and reports a live preview.

A Task Scheduler weekly trigger alone can't skip NYSE holidays that fall on a
weekday (Thanksgiving, Christmas, ...), so that's checked here instead, via
the same trading_calendar the rest of the pipeline uses. See
installer/install.ps1.

Usage: python.exe backtest/run_daily.py
"""
import sys
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bootstrap
import live_preview
import notify
import refresh_chart
import status_store
from close_data import after_close, wait_for_final_close

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "curated.duckdb"


def is_trading_day(d: date) -> bool:
    if not DB_PATH.exists():
        return True  # fresh install, no calendar yet -- let bootstrap run regardless
    con = duckdb.connect(str(DB_PATH), read_only=True)
    row = con.execute("SELECT 1 FROM trading_calendar WHERE trading_date = ?", [d]).fetchone()
    con.close()
    return row is not None


def main() -> None:
    today = date.today()
    if not is_trading_day(today):
        print(f"[run_daily] {today} is not an NYSE trading day -- skipping refresh and notification.")
        return

    data_final = None
    if DB_PATH.exists():
        # After the close, wait for Yahoo's closing bars to settle so the refresh
        # (and the email) use final closing prices, not bars still moving.
        if after_close():
            data_final = wait_for_final_close(today, "[run_daily]")
        refresh_chart.main()
    else:
        print("[run_daily] no database found -- running first-time bootstrap")
        print("[run_daily] this pulls ~36 years of history and will take a few minutes")
        print()
        bootstrap.main()

    try:
        preview = live_preview.build_preview()
    except Exception as exc:
        print(f"[run_daily] could not build the live preview, skipping the status email: {exc}")
        return
    if data_final is not None:
        # False also when today's bar was still missing and the preview fell back to live quotes.
        preview["dataFinal"] = data_final and not preview["isLive"]
    refresh_chart.patch_signal_status(preview)  # dashboard's Signal status panel; never raises
    # Saved regardless of the email, as the baseline the optional final-close
    # check (run_final_check.py) compares against if it's ever re-enabled.
    try:
        status_store.save_baseline(preview, label="daily run")
    except Exception as exc:
        print(f"[run_daily] could not save the baseline: {exc}")
    notify.send_daily_status(preview)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[run_daily] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
