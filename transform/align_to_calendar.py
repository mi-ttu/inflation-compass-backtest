"""Reindex fred_series onto the NYSE trading_calendar, forward-filling
gaps (e.g. bond-market holidays like Columbus Day / Veterans Day that
aren't NYSE holidays) and dropping FRED's own weekday-holiday "."
placeholders.

Replaces the contents of fred_series with the calendar-aligned version.
Must run after build_trading_calendar.py and load_bronze_to_silver.py.

Usage: .venv/Scripts/python.exe transform/align_to_calendar.py
"""
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"


def align_series(con: duckdb.DuckDBPyConnection, series_id: str) -> pd.DataFrame:
    """Align a raw series onto the NYSE calendar via as-of (backward) merge.

    Using merge_asof rather than exact reindex+ffill matters for series
    whose native dates rarely land on a trading day at all — e.g. monthly
    CPI is stamped on the 1st of the month, which is a trading day only
    by coincidence. An exact reindex would leave those rows NaN forever;
    merge_asof correctly carries forward the last known value regardless
    of source frequency (daily or monthly).
    """
    raw = con.execute(
        """
        SELECT observation_date, release_date, value, source
        FROM fred_series
        WHERE series_id = ? AND value IS NOT NULL
        ORDER BY observation_date
        """,
        [series_id],
    ).df()
    if raw.empty:
        raise ValueError(f"No non-null observations for {series_id}")
    raw["observation_date"] = pd.to_datetime(raw["observation_date"])

    first_date, last_date = raw["observation_date"].min(), raw["observation_date"].max()
    calendar = con.execute(
        "SELECT trading_date FROM trading_calendar WHERE trading_date BETWEEN ? AND ? ORDER BY trading_date",
        [first_date.date(), last_date.date()],
    ).df()
    calendar["trading_date"] = pd.to_datetime(calendar["trading_date"])

    aligned = pd.merge_asof(
        calendar,
        raw,
        left_on="trading_date",
        right_on="observation_date",
        direction="backward",
    )
    aligned["is_forward_filled"] = aligned["trading_date"] != aligned["observation_date"]
    aligned["series_id"] = series_id
    aligned = aligned.rename(columns={"trading_date": "observation_date_cal"}).drop(columns=["observation_date"])
    aligned = aligned.rename(columns={"observation_date_cal": "observation_date"})

    return aligned[["series_id", "observation_date", "release_date", "value", "is_forward_filled", "source"]]


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    series_ids = [r[0] for r in con.execute("SELECT DISTINCT series_id FROM fred_series").fetchall()]

    # Compute every aligned frame in memory first, so a failure on one
    # series can't leave the DB with another series half-deleted.
    aligned_frames = {series_id: align_series(con, series_id) for series_id in series_ids}

    con.execute("BEGIN TRANSACTION")
    try:
        for series_id, aligned in aligned_frames.items():
            con.execute("DELETE FROM fred_series WHERE series_id = ?", [series_id])
            con.execute(
                """
                INSERT INTO fred_series
                    (series_id, observation_date, release_date, value, is_forward_filled, source)
                SELECT series_id, observation_date, release_date, value, is_forward_filled, source
                FROM aligned
                """
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    for series_id, aligned in aligned_frames.items():
        ff_count = int(aligned["is_forward_filled"].sum())
        print(
            f"[aligned] {series_id}: {len(aligned)} NYSE trading days "
            f"({aligned['observation_date'].min()} -> {aligned['observation_date'].max()}), "
            f"{ff_count} forward-filled"
        )

    con.close()


if __name__ == "__main__":
    main()
