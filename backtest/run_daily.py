"""Single entry point for the scheduled task (and the standalone installed
app): bootstraps the database from scratch if it doesn't exist yet
(first run after install), otherwise just does the normal incremental
refresh. Either way, ends with an up-to-date interactive_chart.html, then
sends a daily status email reporting the Hybrid (QLD/XLE), Daily variant's
current allocation and the allocation recommended at today's close (see
live_preview.py) -- every trading day this runs, not just on a change
(see notify.py -- silently skipped if email isn't configured).

Scheduled Mon-Fri at 2:30 PM Central, same timing as the MaxAlpha backtest
project (see installer/install.ps1) -- a Task Scheduler weekly trigger
alone can't skip NYSE holidays that fall on a weekday (Thanksgiving,
Christmas, ...), so that's checked here instead, via the same
trading_calendar the rest of the pipeline uses.

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

    if DB_PATH.exists():
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
    notify.send_daily_status(preview)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[run_daily] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
