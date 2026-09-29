"""Inflation Compass -- Enhanced, Levered (2003+): same instrument
substitution as simulate_extended_levered_monthly.py (TQQQ replaces XLK,
ERX replaces XLE, synthetic pre-inception leverage reused unchanged from
that module) but driven by regime_history_enhanced instead of
regime_history_extended -- David Varadi's "Enhanced" Inflation Compass,
which ensembles the momentum lookback across {40, 60, 80} trading days by
majority vote instead of a single 60-day read (see
transform/build_signals_enhanced.py for the exact methodology).

Real data only, no splice: regime_history_enhanced is driven by the real
T5YIE breakeven series (starts 2003-01-02) and real SPDR sector ETFs, not
the Extended variant's EXPINF5YR/Fama-French pre-2003/pre-1998 proxies. The
execution-leg helpers reused below (spliced_leveraged_series,
build_tqqq_extended, build_erx_extended, spliced_series_unlevered) still
apply their own pre-inception synthetic leverage where needed -- TQQQ/ERX's
real inception (2010/2008) is after this variant's 2003 start, so that
splicing is still necessary and correct here, independent of which regime
signal drives the `holding` column.

Usage: .venv/Scripts/python.exe backtest/simulate_enhanced_levered_monthly.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_monthly import load_real_total_return
from simulate_extended_levered_monthly import (
    build_erx_extended,
    build_tqqq_extended,
    spliced_series_unlevered,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("2003-01-01")


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_enhanced ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    series = {
        "TQQQ": build_tqqq_extended(con),
        "ERX": build_erx_extended(con),
        "XLU": spliced_series_unlevered(con, "XLU"),
        "XLP": spliced_series_unlevered(con, "XLP"),
        "IEF": spliced_series_unlevered(con, "IEF"),
    }
    substitution = {"XLE": "ERX", "XLK": "TQQQ"}
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

    print(f"Enhanced, Levered (TQQQ/ERX) -- Monthly: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Enhanced, Levered (TQQQ/ERX)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "enhanced_levered_tqqq_erx_monthly_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
