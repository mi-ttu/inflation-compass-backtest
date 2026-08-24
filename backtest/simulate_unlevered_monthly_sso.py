"""Unlevered Monthly (SSO): the Extended (1990+) regime signal, unchanged,
with SSO (ProShares Ultra S&P 500, 2x) replacing XLK in the goldilocks
regime. XLE, XLU, and the XLP+IEF blend are unchanged real/spliced series
as in simulate_extended_monthly.py -- only the growth-regime holding
becomes 2x-leveraged broad market instead of the GICS tech sector. This is
a partial-leverage hybrid, not a fully levered variant like TQQQ/ERX --
named "Unlevered Monthly (SSO)" to make that explicit rather than implying
full leverage.

SSO launched 2006-06-21. Extended back to 1990 using a synthetic 2x-daily-
compounded ^GSPC proxy pre-inception -- trivial and well-grounded here
(SSO literally targets 2x daily S&P 500, unlike TQQQ/ERX's proxy which
needed an index/sector substitute), so no expense-ratio/financing-drag
caveat beyond the usual "synthetic leverage excludes real fund costs" note.

Usage: .venv/Scripts/python.exe backtest/simulate_unlevered_monthly_sso.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_monthly import load_real_total_return, spliced_series

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")
SSO_LEVERAGE = 2


def build_sso_extended(con: duckdb.DuckDBPyConnection) -> pd.Series:
    gspc = load_real_total_return(con, "^GSPC")
    real_sso = load_real_total_return(con, "SSO")
    inception = real_sso.index.min()
    synthetic = (SSO_LEVERAGE * gspc[gspc.index < inception]).rename("SSO")
    return pd.concat([synthetic, real_sso]).sort_index()


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    series = {
        "SSO": build_sso_extended(con),
        "XLE": spliced_series(con, "XLE"),
        "XLU": spliced_series(con, "XLU"),
        "XLP": spliced_series(con, "XLP"),
        "IEF": spliced_series(con, "IEF"),
    }
    substitution = {"XLK": "SSO"}
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

    print(f"Unlevered Monthly (SSO): {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Unlevered Monthly (SSO)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "unlevered_monthly_sso_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
