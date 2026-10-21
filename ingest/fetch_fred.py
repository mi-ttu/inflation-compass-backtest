"""Pull raw series from FRED's public CSV endpoint (no API key required) --
except T5YIE, the 5-year breakeven inflation rate the strategy's inflation
signal runs on, which comes from the U.S. Treasury first.

T5YIE is FRED's repackaging of two Treasury yields: the 5-year nominal par
yield minus the 5-year real (TIPS) par yield, both published by the Treasury
itself (via the Federal Reserve's H.15 release into FRED). The Treasury is the
origin, so it is the primary source for T5YIE and FRED the fallback; checked
day by day over 2026 the two agree exactly, and Treasury's history starts on
the same day (2003-01-02). The other series (CPIAUCSL, EXPINF5YR, DGS10,
DCOILWTICO) have no such equivalent and stay on FRED.

Fallback chain for T5YIE: Treasury -> FRED -> the previous good pull. FRED
answers HTTP 200 with an HTML "Site Maintenance" page when it is down, so a
response is only used if it really is that series' CSV; a bad response never
overwrites anything, and the run carries on with the last good file. Treasury
data is also refused if it disagrees with the previous pull on the dates they
share (a sign its format changed), so a silent change can't corrupt the signal.

Writes each pull untouched to data/raw/fred/<series_id>/<pulled_at>.csv
plus a .meta.json sidecar (meta "source" says which provider). Never
overwrites a prior pull.

Usage: .venv/Scripts/python.exe ingest/fetch_fred.py
"""
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "fred"

SERIES_IDS = ["T5YIE", "CPIAUCSL", "EXPINF5YR", "DGS10", "DCOILWTICO"]  # DCOILWTICO: WTI crude spot, the pre-2006 proxy for USO
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = {"User-Agent": "inflation-compass-backtest/1.0"}

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
TREASURY_START_YEAR = 2003  # T5YIE's first observation is 2003-01-02
TREASURY_MAX_DISAGREEMENT = 0.05  # percentage points vs the previous pull on shared dates


def has_previous_pull(series_id: str) -> bool:
    return any((RAW_DIR / series_id).glob("*.csv"))


def looks_like_fred_csv(content: bytes, series_id: str) -> bool:
    """FRED answers HTTP 200 with an HTML "Site Maintenance" page when it is
    down, so the status code alone proves nothing -- a real pull starts with
    the CSV header row."""
    head = content[:200].decode("utf-8", errors="replace").lstrip().lower()
    first_line = head.splitlines()[0] if head else ""
    return head.startswith(("observation_date", "date")) and series_id.lower() in first_line


def write_pull(series_id: str, pulled_at: datetime, content: bytes, meta_extra: dict) -> tuple[Path, int]:
    out_dir = RAW_DIR / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pulled_at.strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"{stamp}.csv"
    csv_path.write_bytes(content)

    lines = content.decode("utf-8").strip().splitlines()
    row_count = max(len(lines) - 1, 0)  # minus header
    meta = {
        "series_id": series_id,
        "pulled_at": pulled_at.isoformat(),
        "row_count": row_count,
        "raw_file": str(csv_path.relative_to(PROJECT_ROOT)),
        **meta_extra,
    }
    (out_dir / f"{stamp}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return csv_path, row_count


def fetch_series(series_id: str, pulled_at: datetime) -> Path | None:
    """Returns the saved file, or None when FRED didn't return usable data and
    a previous good pull exists to fall back on (the loader always reads the
    newest file in the folder, so nothing bad is ever written). Raises only
    when there is nothing to fall back on, i.e. a first-ever install."""
    url = FRED_CSV_URL.format(series_id=series_id)
    try:
        resp = requests.get(url, timeout=30, headers=USER_AGENT)
        resp.raise_for_status()
        if not looks_like_fred_csv(resp.content, series_id):
            raise ValueError("response was not CSV data (FRED may be in maintenance)")
    except (requests.RequestException, ValueError) as exc:
        if not has_previous_pull(series_id):
            raise RuntimeError(f"FRED fetch for {series_id} failed and there is no earlier pull to fall back on: {exc}") from exc
        print(f"[fred] {series_id}: WARNING -- {exc}; keeping the previous pull")
        return None

    csv_path, row_count = write_pull(series_id, pulled_at, resp.content, {"source": "fred", "endpoint": url})
    print(f"[fred] {series_id}: {row_count} rows -> {csv_path}")
    return csv_path


# ---- T5YIE from the U.S. Treasury (primary) ----
def _read_previous_series(series_id: str) -> pd.Series | None:
    files = sorted((RAW_DIR / series_id).glob("*.csv"))
    if not files:
        return None
    try:
        df = pd.read_csv(files[-1], na_values=["."])
        df.columns = ["observation_date", "value"]
        df["observation_date"] = pd.to_datetime(df["observation_date"])
        return df.set_index("observation_date")["value"].astype(float)
    except Exception:
        return None


def _treasury_year(kind: str, year: int) -> pd.DataFrame:
    resp = requests.get(TREASURY_URL.format(year=year, kind=kind), timeout=40, headers=USER_AGENT)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")


def treasury_breakeven(years: range | list[int]) -> pd.Series:
    """5-year nominal par yield minus 5-year real (TIPS) par yield, in percent,
    rounded to 2 places the way FRED publishes it."""
    parts = []
    for year in years:
        nominal = _treasury_year("daily_treasury_yield_curve", year)["5 Yr"]
        real = _treasury_year("daily_treasury_real_yield_curve", year)["5 YR"]
        parts.append((nominal - real).dropna())
    s = pd.concat(parts).sort_index().round(2)
    return s[~s.index.duplicated(keep="last")]


def fetch_t5yie_from_treasury(pulled_at: datetime) -> Path:
    """Builds T5YIE from the Treasury's two yield curves and saves it in the
    same CSV layout FRED uses, so the loader needs no special case. Only the
    last two calendar years are pulled when a good history already exists
    (the full 2003-onward pull happens once, on a first install), merged over
    the previous history. Raises if Treasury data is missing, too thin, or
    disagrees with the previous pull."""
    previous = _read_previous_series("T5YIE")
    have_history = previous is not None and previous.dropna().index.min() <= pd.Timestamp("2003-02-01")
    years = [pulled_at.year - 1, pulled_at.year] if have_history else list(range(TREASURY_START_YEAR, pulled_at.year + 1))
    fresh = treasury_breakeven(years)
    if len(fresh) < 5:
        raise ValueError(f"only {len(fresh)} usable rows came back")

    max_diff = None
    if previous is not None:
        shared = fresh.index.intersection(previous.dropna().index)
        if len(shared) >= 5:
            max_diff = float((fresh[shared] - previous[shared]).abs().max())
            if max_diff > TREASURY_MAX_DISAGREEMENT:
                raise ValueError(f"disagrees with the previous pull by up to {max_diff:.2f} points on {len(shared)} shared dates")

    merged = fresh if previous is None else pd.concat([previous[~previous.index.isin(fresh.index)], fresh]).sort_index()
    buf = io.StringIO()
    merged.rename("T5YIE").to_csv(buf, index_label="observation_date", na_rep=".", float_format="%.2f")
    csv_path, row_count = write_pull(
        "T5YIE", pulled_at, buf.getvalue().encode("utf-8"),
        {"source": "treasury", "endpoint": TREASURY_URL.format(year="<year>", kind="daily_treasury_yield_curve / daily_treasury_real_yield_curve"),
         "method": "5 Yr nominal par yield minus 5 YR real par yield", "years_pulled": list(years),
         "max_abs_diff_vs_previous": max_diff},
    )
    diff_note = "" if max_diff is None else f", max diff vs previous pull {max_diff:.2f}"
    print(f"[fred] T5YIE: {row_count} rows from the U.S. Treasury (latest {fresh.index.max().date()}{diff_note}) -> {csv_path}")
    return csv_path


def main() -> None:
    pulled_at = datetime.now(timezone.utc)
    for series_id in SERIES_IDS:
        if series_id == "T5YIE":
            try:
                fetch_t5yie_from_treasury(pulled_at)
                continue
            except Exception as exc:
                print(f"[fred] T5YIE: Treasury source unavailable ({exc}); falling back to FRED")
        fetch_series(series_id, pulled_at)


if __name__ == "__main__":
    main()
