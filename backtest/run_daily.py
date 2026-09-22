"""Single entry point for the scheduled task (and the standalone installed
app): bootstraps the database from scratch if it doesn't exist yet
(first run after install), otherwise just does the normal incremental
refresh. Either way, ends with an up-to-date interactive_chart.html, then
checks whether the Hybrid (QLD/XLE), Daily variant's allocation changed
and emails about it if so (see notify.py -- silently skipped if email
isn't configured).

Usage: python.exe backtest/run_daily.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bootstrap
import notify
import refresh_chart

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "curated.duckdb"


def main() -> None:
    if DB_PATH.exists():
        refresh_chart.main()
    else:
        print("[run_daily] no database found -- running first-time bootstrap")
        print("[run_daily] this pulls ~36 years of history and will take a few minutes")
        print()
        bootstrap.main()

    current_allocation = refresh_chart.build_current_allocation()
    notify.check_and_notify(current_allocation)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[run_daily] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
