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

SERIES_IDS = ["T5YIE", "CPIAUCSL", "EXPINF5YR", "DGS10", "DCOILWTICO"]  # DCOILWTICO: WTI crude spot, the pre-2006 proxy for USO
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def has_previous_pull(series_id: str) -> bool:
    return any((RAW_DIR / series_id).glob("*.csv"))


def looks_like_fred_csv(content: bytes, series_id: str) -> bool:
    """FRED answers HTTP 200 with an HTML "Site Maintenance" page when it is
    down, so the status code alone proves nothing -- a real pull starts with
    the CSV header row."""
    head = content[:200].decode("utf-8", errors="replace").lstrip().lower()
    first_line = head.splitlines()[0] if head else ""
    return head.startswith(("observation_date", "date")) and series_id.lower() in first_line


def fetch_series(series_id: str, pulled_at: datetime) -> Path | None:
    """Returns the saved file, or None when FRED didn't return usable data and
    a previous good pull exists to fall back on (the loader always reads the
    newest file in the folder, so nothing bad is ever written). Raises only
    when there is nothing to fall back on, i.e. a first-ever install."""
    url = FRED_CSV_URL.format(series_id=series_id)
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "inflation-compass-backtest/1.0"})
        resp.raise_for_status()
        if not looks_like_fred_csv(resp.content, series_id):
            raise ValueError("response was not CSV data (FRED may be in maintenance)")
    except (requests.RequestException, ValueError) as exc:
        if not has_previous_pull(series_id):
            raise RuntimeError(f"FRED fetch for {series_id} failed and there is no earlier pull to fall back on: {exc}") from exc
        print(f"[fred] {series_id}: WARNING -- {exc}; keeping the previous pull")
        return None

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
