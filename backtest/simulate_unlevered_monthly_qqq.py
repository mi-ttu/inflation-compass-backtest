"""Unlevered Monthly (QQQ): the Extended (1990+) regime signal, unchanged,
with QQQ (Invesco QQQ Trust, Nasdaq-100) replacing XLK in the goldilocks
regime. XLE, XLU, and the XLP+IEF blend are unchanged real/spliced series
as in simulate_extended_monthly.py -- only the growth-regime holding
switches from the GICS tech sector to the broader, unleveraged Nasdaq-100.

QQQ launched 1999-03-10. Extended back to 1990 using a synthetic 1x ^NDX
(Nasdaq-100 index) proxy pre-inception -- exact by construction, since QQQ
tracks ^NDX 1:1 before fees, same reasoning already used for TQQQ's 3x ^NDX
proxy in simulate_extended_levered_daily_signal.py.

Usage: .venv/Scripts/python.exe backtest/simulate_unlevered_monthly_qqq.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_monthly import load_real_total_return, spliced_series

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")


def build_qqq_extended(con: duckdb.DuckDBPyConnection) -> pd.Series:
    ndx = load_real_total_return(con, "^NDX")
    real_qqq = load_real_total_return(con, "QQQ")
    inception = real_qqq.index.min()
    synthetic = ndx[ndx.index < inception].rename("QQQ")
    return pd.concat([synthetic, real_qqq]).sort_index()


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
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

    print(f"Unlevered Monthly (QQQ): {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Unlevered Monthly (QQQ)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "unlevered_monthly_qqq_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
