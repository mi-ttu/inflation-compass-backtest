"""Populate trading_calendar with NYSE sessions.

Every other silver table is reindexed onto this calendar, so it's built
first and independently of any raw data pull.

Usage: .venv/Scripts/python.exe transform/build_trading_calendar.py
"""
from pathlib import Path

import duckdb
import pandas_market_calendars as mcal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

START = "1993-01-01"  # covers SPY's earliest possible history
END = "2026-12-31"


def main() -> None:
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=START, end_date=END)
    trading_dates = schedule.index.date

    con = duckdb.connect(str(DB_PATH))
    con.execute("DELETE FROM trading_calendar")
    con.executemany(
        "INSERT INTO trading_calendar (trading_date) VALUES (?)",
        [(d,) for d in trading_dates],
    )
    count = con.execute("SELECT COUNT(*) FROM trading_calendar").fetchone()[0]
    con.close()
    print(f"trading_calendar: {count} NYSE sessions, {trading_dates.min()} -> {trading_dates.max()}")


if __name__ == "__main__":
    main()
