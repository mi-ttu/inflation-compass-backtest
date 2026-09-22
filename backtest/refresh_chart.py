"""End-to-end refresh for the interactive chart artifact: re-pull market data,
rebuild the signal engine and the five backtest variants the chart displays
(Levered TQQQ/ERX monthly, Levered TQQQ/ERX daily-signal, Unlevered QQQ
monthly, Hybrid QLD-goldilocks/XLE-reflation monthly, and its daily-signal
cadence), then patch the fresh daily-return series, the monthly/annual
returns table, the regime pie-chart summary, and the current-allocation
banner into backtest/interactive_chart.html in place.

This script only regenerates the local HTML file -- it does not publish
anything. After it succeeds, publish backtest/interactive_chart.html to the
existing artifact URL (see backtest/ARTIFACT_URL.txt) via Claude's Artifact
tool, passing that URL so the same page updates instead of creating a new one.

Usage: .venv/Scripts/python.exe backtest/refresh_chart.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_DIR = PROJECT_ROOT / "backtest"
CHART_PATH = BACKTEST_DIR / "interactive_chart.html"
# Whatever interpreter is currently running this script -- the dev venv's
# python.exe locally, or the standalone app's embedded runtime once
# installed. Never hardcode a venv path here: it won't exist post-install.
PYTHON = Path(sys.executable)

PIPELINE_STEPS = [
    ("ingest/fetch_yfinance.py", "ingest"),
    ("ingest/fetch_fred.py", "ingest"),
    ("transform/load_bronze_to_silver.py", "transform"),
    ("transform/align_to_calendar.py", "transform"),
    ("transform/build_total_return_index.py", "transform"),
    ("transform/build_signals_extended.py", "transform"),
    ("backtest/simulate_extended_levered_monthly.py", "backtest"),
    ("backtest/simulate_extended_levered_daily_signal.py", "backtest"),
    ("backtest/simulate_unlevered_monthly_qqq.py", "backtest"),
    ("backtest/simulate_hybrid_qld_goldilocks_xle_reflation.py", "backtest"),
    ("backtest/simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal.py", "backtest"),
]

REGIME_MAP = {
    "QQQ": "goldilocks",
    "XLE": "reflation",
    "XLU": "stagflation",
    "XLP+IEF_5050": "disinflation",
}
REPORT_START = "1990-01-01"


def run_pipeline() -> None:
    for rel_path, _stage in PIPELINE_STEPS:
        script = PROJECT_ROOT / rel_path
        print(f"[refresh] running {rel_path} ...")
        # The standalone app's embedded Python runtime uses a ._pth file
        # that, unlike a normal install, does NOT auto-add the running
        # script's own directory to sys.path -- so a same-directory
        # sibling import (e.g. `from _levered_common import ...`) would
        # otherwise fail there even though it works fine in a dev venv.
        # Setting PYTHONPATH explicitly makes this work identically in
        # both environments.
        env = {**os.environ, "PYTHONPATH": str(script.parent)}
        result = subprocess.run([str(PYTHON), str(script)], cwd=str(script.parent), env=env)
        if result.returncode != 0:
            raise RuntimeError(f"{rel_path} exited with code {result.returncode} -- aborting refresh")


def load_series(csv_name: str) -> pd.Series:
    df = pd.read_csv(BACKTEST_DIR / csv_name, parse_dates=["trading_date"])
    df = df[df["trading_date"] >= REPORT_START].sort_values("trading_date")
    return df.set_index("trading_date")


def build_daily_blob() -> dict:
    levered = load_series("extended_levered_tqqq_erx_returns.csv")
    levered_daily = load_series("extended_levered_daily_signal_returns.csv")
    unlevered = load_series("unlevered_monthly_qqq_returns.csv")
    hybrid_qld_xle = load_series("hybrid_qld_goldilocks_xle_reflation_returns.csv")
    hybrid_qld_xle_daily = load_series("hybrid_qld_goldilocks_xle_reflation_daily_signal_returns.csv")

    dates = sorted(
        set(levered.index) & set(levered_daily.index) & set(unlevered.index)
        & set(hybrid_qld_xle.index) & set(hybrid_qld_xle_daily.index)
    )
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]

    return {
        "dates": date_strs,
        "levered": [round(float(levered.loc[d, "model_return"]), 4) for d in dates],
        "unlevered": [round(float(unlevered.loc[d, "model_return"]), 4) for d in dates],
        "spy": [round(float(unlevered.loc[d, "spy_return"]), 4) for d in dates],
        "levered_daily": [round(float(levered_daily.loc[d, "model_return"]), 4) for d in dates],
        "hybrid_qld_xle": [round(float(hybrid_qld_xle.loc[d, "model_return"]), 4) for d in dates],
        "hybrid_qld_xle_daily": [round(float(hybrid_qld_xle_daily.loc[d, "model_return"]), 4) for d in dates],
    }


def build_monthly_table() -> dict:
    df = load_series("unlevered_monthly_qqq_returns.csv")
    df["period"] = df.index.to_period("M")
    holding_by_month = df.groupby("period")["traded_holding"].agg(lambda s: s.value_counts().idxmax())
    monthly = (1 + df["model_return"]).resample("ME").prod() - 1
    monthly.index = monthly.index.to_period("M")

    years = sorted(set(p.year for p in monthly.index))
    rows = []
    for y in years:
        month_vals, month_regimes, year_vals = [], [], []
        for m in range(1, 13):
            key = pd.Period(year=y, month=m, freq="M")
            if key in monthly.index:
                v = float(monthly.loc[key])
                month_vals.append(round(v * 100, 2))
                month_regimes.append(REGIME_MAP[holding_by_month.loc[key]])
                year_vals.append(v)
            else:
                month_vals.append(None)
                month_regimes.append(None)
        if year_vals:
            total = 1.0
            for v in year_vals:
                total *= 1 + v
            total_pct = round((total - 1) * 100, 2)
        else:
            total_pct = None
        rows.append({"year": y, "m": month_vals, "r": month_regimes, "total": total_pct})

    last_date = df.index.max().strftime("%Y-%m-%d")
    return {"rows": rows, "lastUpdate": last_date}


TRADED_REGIME_MAP = {
    "QLD": "goldilocks",
    "XLE": "reflation",
    "XLU": "stagflation",
    "XLP+IEF_5050": "disinflation",
}


def build_current_allocation() -> dict:
    monthly = load_series("hybrid_qld_goldilocks_xle_reflation_returns.csv")
    daily = load_series("hybrid_qld_goldilocks_xle_reflation_daily_signal_returns.csv")
    monthly_holding = monthly["traded_holding"].iloc[-1]
    daily_holding = daily["traded_holding"].iloc[-1]
    return {
        "asOf": max(monthly.index.max(), daily.index.max()).strftime("%Y-%m-%d"),
        "monthly": {"holding": monthly_holding, "regime": TRADED_REGIME_MAP[monthly_holding]},
        "daily": {"holding": daily_holding, "regime": TRADED_REGIME_MAP[daily_holding]},
    }


TRADED_REGIME_CODE = {"QLD": "G", "XLE": "R", "XLU": "S", "XLP+IEF_5050": "D"}


def canonical_doy(month: int, day: int) -> int:
    # 2020 is a leap year, so this gives a fixed 366-slot calendar position
    # for any (month, day) -- Feb 29 always lands on slot 60, Dec 31 always
    # on slot 366 -- so every year's row aligns on the same column
    # regardless of whether that particular year was a leap year.
    return pd.Timestamp(year=2020, month=month, day=day).dayofyear


def build_daily_calendar_table() -> dict:
    """Run-length encode the daily-signal variant's holding periods (a "run"
    is a maximal stretch of consecutive trading days holding the same
    instrument), then forward-fill each run across the weekends/holidays
    that follow it so the calendar grid shows one continuous block of color
    per allocation decision -- the position doesn't change over a weekend,
    there's just no trading-day return recorded for those calendar days.
    Each grid cell stores an index into `runs` rather than repeating the
    run's start/end/return per day, both for a smaller payload and so every
    cell in one block shares exactly one tooltip describing the whole
    holding period.
    """
    df = load_series("hybrid_qld_goldilocks_xle_reflation_daily_signal_returns.csv")
    df["run_id"] = (df["traded_holding"] != df["traded_holding"].shift()).cumsum()

    runs = []
    run_id_to_idx = {}
    for i, (run_id, grp) in enumerate(df.groupby("run_id")):
        holding = grp["traded_holding"].iloc[0]
        total = 1.0
        for v in grp["model_return"]:
            total *= 1 + v
        runs.append({
            "start": grp.index.min().strftime("%Y-%m-%d"),
            "end": grp.index.max().strftime("%Y-%m-%d"),
            "holding": holding,
            "regime": TRADED_REGIME_CODE[holding],
            "returnPct": round((total - 1) * 100, 2),
        })
        run_id_to_idx[run_id] = i

    trading_run_idx = df["run_id"].map(run_id_to_idx)  # indexed by trading_date
    full_range = pd.date_range(df.index.min(), df.index.max(), freq="D")
    run_idx_by_calendar_day = trading_run_idx.reindex(full_range).ffill()

    years = sorted(set(full_range.year))
    rows = []
    for y in years:
        year_dates = full_range[full_range.year == y]
        year_idx = run_idx_by_calendar_day.reindex(year_dates)
        day_map = {
            canonical_doy(d.month, d.day): int(idx)
            for d, idx in zip(year_dates, year_idx) if pd.notna(idx)
        }
        days = [day_map.get(d) for d in range(1, 367)]

        year_returns = df.loc[df.index.year == y, "model_return"].values
        if len(year_returns):
            total = 1.0
            for v in year_returns:
                total *= 1 + v
            total_pct = round((total - 1) * 100, 2)
        else:
            total_pct = None
        rows.append({"year": int(y), "days": days, "total": total_pct})

    last_date = df.index.max().strftime("%Y-%m-%d")
    return {"runs": runs, "rows": rows, "lastUpdate": last_date}


def build_regime_summary() -> dict:
    df = load_series("unlevered_monthly_qqq_returns.csv")
    df["period"] = df.index.to_period("M")
    holding_by_month = df.groupby("period")["traded_holding"].agg(lambda s: s.value_counts().idxmax())
    monthly = (1 + df["model_return"]).resample("ME").prod() - 1
    monthly.index = monthly.index.to_period("M")
    regime_of_month = holding_by_month.map(REGIME_MAP)

    months_count = regime_of_month.value_counts()
    time_share = (months_count / months_count.sum() * 100).round(1).to_dict()

    log_ret = np.log(1 + monthly)
    by_regime_logret = log_ret.groupby(regime_of_month).sum()
    total_logret = log_ret.sum()
    return_share = (by_regime_logret / total_logret * 100).round(1).to_dict()

    return {"time": time_share, "returnShare": return_share}


def replace_const(text: str, const_name: str, payload: dict) -> str:
    marker = f"const {const_name} = "
    start = text.find(marker)
    if start == -1:
        raise RuntimeError(f"could not find `{marker}` in {CHART_PATH.name}")
    json_start = start + len(marker)
    end = text.find(";\n", json_start)
    if end == -1:
        raise RuntimeError(f"could not find terminator for `{const_name}` in {CHART_PATH.name}")
    new_json = json.dumps(payload)
    return text[:json_start] + new_json + text[end:]


def patch_chart(
    daily: dict, monthly_table: dict, regime_summary: dict, current_allocation: dict, daily_calendar: dict
) -> None:
    text = CHART_PATH.read_text(encoding="utf-8")
    text = replace_const(text, "MONTHLY_TABLE_QQQ", monthly_table)
    text = replace_const(text, "DAILY", daily)
    text = replace_const(text, "REGIME_SUMMARY", regime_summary)
    text = replace_const(text, "CURRENT_ALLOCATION", current_allocation)
    text = replace_const(text, "DAILY_CALENDAR_QLD_XLE", daily_calendar)
    CHART_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    run_pipeline()

    daily = build_daily_blob()
    monthly_table = build_monthly_table()
    regime_summary = build_regime_summary()
    current_allocation = build_current_allocation()
    daily_calendar = build_daily_calendar_table()

    patch_chart(daily, monthly_table, regime_summary, current_allocation, daily_calendar)

    print()
    print(f"[refresh] chart data through {daily['dates'][-1]} patched into {CHART_PATH}")
    print("[refresh] next step: publish backtest/interactive_chart.html via the Artifact tool,")
    print("          passing url=<the existing artifact URL> so it updates in place.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # surface pipeline/patch failures clearly to the caller
        print(f"[refresh] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
