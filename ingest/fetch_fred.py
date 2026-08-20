"""Pull raw series from FRED's public CSV endpoint (no API key required).

Writes each pull untouched to data/raw/fred/<series_id>/<pulled_at>.csv
plus a .meta.json sidecar. Never overwrites a prior pull.

Usage: .venv/Scripts/python.exe ingest/fetch_fred.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "fred"

SERIES_IDS = ["T5YIE", "CPIAUCSL"]
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_series(series_id: str, pulled_at: datetime) -> Path:
    url = FRED_CSV_URL.format(series_id=series_id)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "inflation-compass-backtest/1.0"})
    resp.raise_for_status()

    out_dir = RAW_DIR / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pulled_at.strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"{stamp}.csv"
    csv_path.write_bytes(resp.content)

    lines = resp.content.decode("utf-8").strip().splitlines()
    row_count = max(len(lines) - 1, 0)  # minus header

    meta = {
        "source": "fred",
        "series_id": series_id,
        "endpoint": url,
        "pulled_at": pulled_at.isoformat(),
        "row_count": row_count,
        "raw_file": str(csv_path.relative_to(PROJECT_ROOT)),
    }
    meta_path = out_dir / f"{stamp}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[fred] {series_id}: {row_count} rows -> {csv_path}")
    return csv_path


def main() -> None:
    pulled_at = datetime.now(timezone.utc)
    for series_id in SERIES_IDS:
        fetch_series(series_id, pulled_at)


if __name__ == "__main__":
    main()
