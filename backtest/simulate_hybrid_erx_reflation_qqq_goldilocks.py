"""Inflation Compass -- Hybrid, Monthly (1990+): a mixed-leverage variant of
the Extended regime signal (unchanged) that levers up ONLY the reflation
regime -- ERX (2x energy) replaces XLE -- while every other regime stays
unlevered: QQQ (Nasdaq-100, real 1x) replaces XLK in goldilocks (same
substitution as the Unlevered Monthly (QQQ) variant), and XLU / XLP+IEF are
untouched.

Reuses the project's already-built proxy chains rather than re-deriving
them:
    - ERX pre-2008-11-19: build_erx_extended() from
      simulate_extended_levered_monthly.py -- 2x-daily-compounded
      [Fama-French Enrgy pre-1998, chained with real XLE 1998-2008].
    - QQQ pre-1999-03-10: build_qqq_extended() from
      simulate_unlevered_monthly_qqq.py -- 1x ^NDX (the index QQQ tracks).
    - XLU / XLP+IEF: spliced_series_unlevered() from
      simulate_extended_levered_monthly.py -- Fama-French pre-1998 chained
      with real SPDR/DGS10-proxy data, unchanged from every unlevered
      variant already built.

The synthetic ERX segment carries no expense ratio / daily financing cost,
so it's a mild optimistic upper bound relative to a real fund, on top of
the volatility-decay effects daily compounding does capture.

Usage: .venv/Scripts/python.exe backtest/simulate_hybrid_erx_reflation_qqq_goldilocks.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_levered_monthly import build_erx_extended, spliced_series_unlevered
from simulate_extended_monthly import load_real_total_return
from simulate_unlevered_monthly_qqq import build_qqq_extended

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    series = {
        "ERX": build_erx_extended(con),
        "QQQ": build_qqq_extended(con),
        "XLU": spliced_series_unlevered(con, "XLU"),
        "XLP": spliced_series_unlevered(con, "XLP"),
        "IEF": spliced_series_unlevered(con, "IEF"),
    }
    substitution = {"XLE": "ERX", "XLK": "QQQ"}
    gspc = load_real_total_return(con, "^GSPC")

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        original_holding = regime.loc[i, "holding"]
        traded_holding = substitution.get(original_holding, original_holding)
        dates = pd.DatetimeIndex([d for d in gspc.index if start < d <= end])

        if traded_holding == "XLP+IEF_5050":
            leg_xlp = (1 + series["XLP"].reindex(dates)).cumprod()
            leg_ief = (1 + series["IEF"].reindex(dates)).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = series[traded_holding].reindex(dates)

        spy_ret = gspc.reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "original_holding": original_holding, "traded_holding": traded_holding,
                "model_return": model_ret.loc[dt], "spy_return": spy_ret.loc[dt],
            })

    return pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    daily = build_daily_equity(con)
    con.close()

    daily = daily[daily["trading_date"] >= REPORT_START].reset_index(drop=True)

    print(f"Hybrid (ERX reflation / QQQ goldilocks) -- Monthly: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Hybrid (ERX/QQQ)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "hybrid_erx_reflation_qqq_goldilocks_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
