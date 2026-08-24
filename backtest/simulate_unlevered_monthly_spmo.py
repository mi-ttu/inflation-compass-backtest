"""Unlevered Monthly (SPMO): the Extended (1990+) regime signal, unchanged,
with SPMO (Invesco S&P 500 Momentum ETF) replacing XLK in the goldilocks
regime. XLE, XLU, and the XLP+IEF blend are unchanged real/spliced series.

Unlike TECL/QLD/TQQQ/SSO, SPMO has no defensible pre-inception proxy here:
it's a single-factor (momentum) product cutting across all S&P 500 sectors,
not a sector or leverage-of-an-index product, so neither the Fama-French
12-industry classification nor a simple multiple of an index return
represents "what SPMO would have done" before it existed. Rather than
fabricate one, this backtest is restricted to SPMO's real trading history
only: 2015-10-12 onward -- a real, deliberate constraint, not an oversight.

Usage: .venv/Scripts/python.exe backtest/simulate_unlevered_monthly_spmo.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_monthly import load_real_total_return

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"


def build_daily_equity(con: duckdb.DuckDBPyConnection, report_start: pd.Timestamp) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended WHERE decision_date >= ? ORDER BY decision_date",
        [report_start.date()],
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    tickers = ["SPMO", "XLE", "XLU", "XLP", "IEF", "^GSPC"]
    real = {t: load_real_total_return(con, t) for t in tickers}
    substitution = {"XLK": "SPMO"}
    gspc = real["^GSPC"]

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        original_holding = regime.loc[i, "holding"]
        traded_holding = substitution.get(original_holding, original_holding)
        dates = pd.DatetimeIndex([d for d in gspc.index if start < d <= end])

        if traded_holding == "XLP+IEF_5050":
            leg_xlp = (1 + real["XLP"].reindex(dates)).cumprod()
            leg_ief = (1 + real["IEF"].reindex(dates)).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = real[traded_holding].reindex(dates)

        spy_ret = gspc.reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "original_holding": original_holding, "traded_holding": traded_holding,
                "model_return": model_ret.loc[dt], "spy_return": spy_ret.loc[dt],
            })

    return pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    spmo_inception = load_real_total_return(con, "SPMO").index.min()
    print(f"SPMO real inception: {spmo_inception.date()} -- backtest restricted to this onward (no synthetic proxy)")
    print()

    daily = build_daily_equity(con, spmo_inception)
    con.close()

    print(f"Unlevered Monthly (SPMO): {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Unlevered Monthly (SPMO)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "unlevered_monthly_spmo_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
