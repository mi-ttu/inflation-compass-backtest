"""Pull the Fama-French 12 Industry Portfolios (daily) from Ken French's
Data Library (Dartmouth) -- free, public, academic source, no API key.

Used as a pre-1998 proxy for sector/industry returns, since the SPDR
sector ETFs (XLE, XLK, XLU, XLP, XLI, XLF, XLB, XLV) didn't exist before
December 1998. See transform/build_signals_extended.py for the documented
industry-to-sector mapping and how this data is spliced with the real
SPDR-based series.

Writes the raw zip and extracted CSV untouched to
data/raw/famafrench/<pulled_at>/, plus a .meta.json sidecar.

Usage: .venv/Scripts/python.exe ingest/fetch_famafrench.py
"""
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "famafrench"
URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/12_Industry_Portfolios_daily_CSV.zip"


def main() -> None:
    pulled_at = datetime.now(timezone.utc)
    stamp = pulled_at.strftime("%Y%m%dT%H%M%SZ")
    out_dir = RAW_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    resp = requests.get(URL, timeout=60, headers={"User-Agent": "inflation-compass-backtest/1.0"})
    resp.raise_for_status()
    zip_path = out_dir / "12_Industry_Portfolios_daily_CSV.zip"
    zip_path.write_bytes(resp.content)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
        extracted_names = zf.namelist()

    meta = {
        "source": "ken_french_data_library",
        "identifier": "12_industry_portfolios_daily",
        "endpoint": URL,
        "pulled_at": pulled_at.isoformat(),
        "extracted_files": extracted_names,
        "raw_file": str(zip_path.relative_to(PROJECT_ROOT)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[famafrench] pulled -> {out_dir}, extracted: {extracted_names}")


if __name__ == "__main__":
    main()
