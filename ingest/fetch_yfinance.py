"""Pull raw daily OHLCV + dividend history from Yahoo Finance via yfinance.

Writes each pull untouched to data/raw/yfinance/<ticker>/<pulled_at>.csv
plus a .meta.json sidecar. Never overwrites a prior pull.

Uses auto_adjust=False so we get raw OHLC, a separate 'Adj Close' column
(kept only for reconciliation), and a 'Dividends' column (the raw
ingredient for our own total-return reconstruction in transform/).

Usage: .venv/Scripts/python.exe ingest/fetch_yfinance.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "yfinance"

TICKERS = ["SPY", "XLE", "XLK", "XLU", "XLP", "IEF", "XLI", "XLF", "XLB", "XLV", "TECL", "ERX", "QLD", "TQQQ", "^GSPC"]


def fetch_ticker(ticker: str, pulled_at: datetime) -> Path:
    hist = yf.Ticker(ticker).history(
        period="max",
        auto_adjust=False,
        actions=True,
    )

    out_dir = RAW_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pulled_at.strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"{stamp}.csv"
    hist.to_csv(csv_path)

    meta = {
        "source": "yfinance",
        "ticker": ticker,
        "pulled_at": pulled_at.isoformat(),
        "row_count": len(hist),
        "date_range_start": str(hist.index.min().date()) if len(hist) else None,
        "date_range_end": str(hist.index.max().date()) if len(hist) else None,
        "raw_file": str(csv_path.relative_to(PROJECT_ROOT)),
    }
    meta_path = out_dir / f"{stamp}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[yfinance] {ticker}: {len(hist)} rows, {meta['date_range_start']} -> {meta['date_range_end']}")
    return csv_path


def main() -> None:
    pulled_at = datetime.now(timezone.utc)
    for ticker in TICKERS:
        fetch_ticker(ticker, pulled_at)


if __name__ == "__main__":
    main()
