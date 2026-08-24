"""Per-regime return analysis for the Unlevered Monthly (QQQ) variant.

Reports the average monthly return of the held position within each of the
four macro regimes -- same framing as the original blog post's "Average
monthly return of the held position in each macro regime" chart -- using
QQQ in place of XLK for the goldilocks regime, per the already-built
Unlevered Monthly (QQQ) variant.

Usage: .venv/Scripts/python.exe backtest/regime_returns_analysis.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from simulate_extended_monthly import load_real_total_return, spliced_series
from simulate_unlevered_monthly_qqq import build_qqq_extended

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")
TRADING_DAYS_PER_YEAR = 252

REGIME_LABELS = {
    "XLE": "Reflation",
    "XLK": "Goldilocks",
    "XLU": "Stagflation",
    "XLP+IEF_5050": "Disinflationary slowdown",
}


def monthly_period_returns(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended WHERE decision_date >= ? ORDER BY decision_date",
        [REPORT_START.date()],
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    series = {
        "QQQ": build_qqq_extended(con),
        "XLE": spliced_series(con, "XLE"),
        "XLU": spliced_series(con, "XLU"),
        "XLP": spliced_series(con, "XLP"),
        "IEF": spliced_series(con, "IEF"),
    }
    substitution = {"XLK": "QQQ"}

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        original_holding = regime.loc[i, "holding"]
        traded_holding = substitution.get(original_holding, original_holding)

        if traded_holding == "XLP+IEF_5050":
            xlp_seg = series["XLP"][(series["XLP"].index > start) & (series["XLP"].index <= end)]
            ief_seg = series["IEF"][(series["IEF"].index > start) & (series["IEF"].index <= end)]
            r_xlp = (1 + xlp_seg).prod() - 1
            r_ief = (1 + ief_seg).prod() - 1
            period_return = 0.5 * r_xlp + 0.5 * r_ief
        else:
            seg = series[traded_holding][(series[traded_holding].index > start) & (series[traded_holding].index <= end)]
            period_return = (1 + seg).prod() - 1

        rows.append({
            "period_end": end, "original_holding": original_holding,
            "regime": REGIME_LABELS[original_holding], "monthly_return": period_return,
        })

    return pd.DataFrame(rows)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    monthly = monthly_period_returns(con)
    con.close()

    summary = monthly.groupby("regime")["monthly_return"].agg(
        months="count",
        mean_monthly=lambda x: x.mean(),
        median_monthly=lambda x: x.median(),
        std_monthly=lambda x: x.std(ddof=1),
        win_rate=lambda x: (x > 0).mean(),
        best_month=lambda x: x.max(),
        worst_month=lambda x: x.min(),
    )
    summary["annualized_equiv"] = (1 + summary["mean_monthly"]) ** 12 - 1
    summary["sharpe_within_regime"] = (summary["mean_monthly"] * 12) / (summary["std_monthly"] * np.sqrt(12))

    order = ["Reflation", "Goldilocks", "Stagflation", "Disinflationary slowdown"]
    summary = summary.reindex(order)

    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(f"Per-regime monthly returns, Unlevered Monthly (QQQ), {monthly['period_end'].min().date()} -> {monthly['period_end'].max().date()}")
    print()
    print(summary)

    # Contribution check: overall CAGR reconstructed by compounding all months in order
    overall_equity = (1 + monthly.sort_values("period_end")["monthly_return"]).prod()
    n_years = len(monthly) / 12
    overall_cagr = overall_equity ** (1 / n_years) - 1
    print()
    print(f"Sanity check -- full strategy CAGR reconstructed from these monthly periods: {overall_cagr:.2%}")

    out_path = PROJECT_ROOT / "backtest" / "regime_monthly_returns.csv"
    monthly.to_csv(out_path, index=False)
    print(f"\nSaved {len(monthly)} monthly period returns to {out_path}")


if __name__ == "__main__":
    main()
