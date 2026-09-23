"""Load the latest bronze (raw) pull per source/identifier into curated
DuckDB tables. Idempotent: re-running overwrites rows by primary key,
never duplicates.

Does NOT forward-fill or reindex onto the trading calendar — that
happens in align_to_calendar.py, as a separate, explicit step.

Usage: .venv/Scripts/python.exe transform/load_bronze_to_silver.py
"""
import json
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def latest_pull(source_dir: Path) -> tuple[Path, Path]:
    """Return (csv_path, meta_path) for the most recent pull in a dir."""
    csvs = sorted(source_dir.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No raw pulls found in {source_dir}")
    csv_path = csvs[-1]
    meta_path = csv_path.with_suffix("").with_suffix(".meta.json")
    return csv_path, meta_path


def load_fred(con: duckdb.DuckDBPyConnection) -> None:
    fred_dir = RAW_DIR / "fred"
    for series_dir in sorted(fred_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        series_id = series_dir.name
        csv_path, meta_path = latest_pull(series_dir)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pulled_at = datetime.fromisoformat(meta["pulled_at"])

        df = pd.read_csv(csv_path, na_values=["."])
        df.columns = ["observation_date", "value"]
        df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
        df["series_id"] = series_id
        df["release_date"] = pulled_at.date()
        df["is_forward_filled"] = False
        df["source"] = "FRED"

        con.execute("DELETE FROM fred_series WHERE series_id = ?", [series_id])
        con.execute(
            """
            INSERT INTO fred_series
                (series_id, observation_date, release_date, value, is_forward_filled, source)
            SELECT series_id, observation_date, release_date, value, is_forward_filled, source
            FROM df
            """
        )
        print(f"[silver] fred_series/{series_id}: {len(df)} rows")

        log_ingestion(con, meta, csv_path)


def load_yfinance(con: duckdb.DuckDBPyConnection) -> None:
    yf_dir = RAW_DIR / "yfinance"
    for ticker_dir in sorted(yf_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name
        csv_path, meta_path = latest_pull(ticker_dir)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        df = pd.read_csv(csv_path)
        df["trading_date"] = pd.to_datetime(df["Date"], utc=True).dt.date
        df["ticker"] = ticker
        df["source"] = "yfinance"

        prices = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
                "Adj Close": "vendor_adj_close",
            }
        )[
            ["ticker", "trading_date", "open", "high", "low", "close", "volume", "vendor_adj_close", "source"]
        ]
        # A pull made before today's close includes a partial in-progress
        # bar for the current session (yfinance leaves close as NaN until
        # the session actually finishes) -- drop it rather than let it
        # violate the NOT NULL constraint. This is expected now that the
        # scheduled refresh runs at 2:30 PM Central, before the 4pm ET
        # close: "latest data" naturally means yesterday's finalized close
        # until today's actually settles.
        incomplete = prices["close"].isna()
        if incomplete.any():
            dropped_dates = prices.loc[incomplete, "trading_date"].tolist()
            print(f"[silver] {ticker}: dropping {incomplete.sum()} incomplete in-progress bar(s): {dropped_dates}")
            prices = prices[~incomplete]
        con.execute("DELETE FROM equity_prices WHERE ticker = ?", [ticker])
        con.execute(
            """
            INSERT INTO equity_prices
                (ticker, trading_date, open, high, low, close, volume, vendor_adj_close, source)
            SELECT ticker, trading_date, open, high, low, close, volume, vendor_adj_close, source
            FROM prices
            """
        )

        divs = df[df["Dividends"] > 0][["ticker", "trading_date", "Dividends", "source"]].rename(
            columns={"trading_date": "ex_date", "Dividends": "amount"}
        )
        con.execute("DELETE FROM equity_dividends WHERE ticker = ?", [ticker])
        if len(divs):
            con.execute(
                """
                INSERT INTO equity_dividends (ticker, ex_date, amount, source)
                SELECT ticker, ex_date, amount, source FROM divs
                """
            )

        print(f"[silver] equity_prices/{ticker}: {len(prices)} rows, {len(divs)} dividend events")
        log_ingestion(con, meta, csv_path)


_next_log_id = [None]


def log_ingestion(con: duckdb.DuckDBPyConnection, meta: dict, csv_path: Path) -> None:
    if _next_log_id[0] is None:
        row = con.execute("SELECT COALESCE(MAX(ingestion_id), 0) FROM ingestion_log").fetchone()
        _next_log_id[0] = row[0] + 1
    ingestion_id = _next_log_id[0]
    _next_log_id[0] += 1

    identifier = meta.get("series_id") or meta.get("ticker") or meta.get("identifier", "unknown")
    con.execute(
        """
        INSERT INTO ingestion_log
            (ingestion_id, source, identifier, endpoint, pulled_at, date_range_start, date_range_end, row_count, raw_file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ingestion_id,
            meta["source"],
            identifier,
            meta.get("endpoint"),
            meta["pulled_at"],
            meta.get("date_range_start"),
            meta.get("date_range_end"),
            meta.get("row_count"),
            str(csv_path.relative_to(PROJECT_ROOT)),
        ],
    )


def load_famafrench(con: duckdb.DuckDBPyConnection) -> None:
    ff_dir = RAW_DIR / "famafrench"
    pull_dirs = sorted(d for d in ff_dir.iterdir() if d.is_dir())
    if not pull_dirs:
        return
    pull_dir = pull_dirs[-1]
    meta = json.loads((pull_dir / "meta.json").read_text(encoding="utf-8"))
    csv_path = pull_dir / "12_Industry_Portfolios_Daily.csv"

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    header_idx = next(i for i, line in enumerate(lines) if "Average Value Weighted Returns" in line)
    columns = [c.strip() for c in lines[header_idx + 1].split(",")][1:]  # drop leading blank (date) column
    data_start = header_idx + 2
    data_end = next(i for i in range(data_start, len(lines)) if not lines[i].strip())

    rows = []
    for line in lines[data_start:data_end]:
        parts = [p.strip() for p in line.split(",")]
        trading_date = pd.to_datetime(parts[0], format="%Y%m%d").date()
        for industry, raw_value in zip(columns, parts[1:], strict=True):
            value = float(raw_value)
            if value in (-99.99, -999):
                continue
            rows.append((industry, trading_date, value / 100.0))

    df = pd.DataFrame(rows, columns=["industry", "trading_date", "daily_return"])
    con.execute("DELETE FROM famafrench_industry_returns")
    con.execute(
        "INSERT INTO famafrench_industry_returns (industry, trading_date, daily_return) "
        "SELECT industry, trading_date, daily_return FROM df"
    )
    print(f"[silver] famafrench_industry_returns: {len(df)} rows, {len(columns)} industries")

    log_ingestion(con, meta, csv_path)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    con.execute("DELETE FROM ingestion_log")
    load_fred(con)
    load_yfinance(con)
    load_famafrench(con)
    con.close()


if __name__ == "__main__":
    main()
