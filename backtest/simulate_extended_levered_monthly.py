"""Inflation Compass -- Extended, Levered (1990+): the same
regime_history_extended signal (unchanged from simulate_extended_monthly.py
-- still driven by unlevered SPY/^GSPC and the spliced sector basket) but
TQQQ replaces XLK and ERX replaces XLE at execution, same substitution
pattern as backtest/_levered_common.py's TQQQ/ERX variant -- extended back
to 1990 using synthetic daily-leveraged proxies before each fund's real
inception:

    TQQQ (3x Nasdaq-100) pre-2010-02-11:
        3x-daily-compounded ^NDX (the actual Nasdaq-100 index TQQQ tracks,
        free via Yahoo back to 1985-10-01) -- NOT XLK. XLK (GICS tech
        sector) and Nasdaq-100 are meaningfully different benchmarks, as
        our own TECL/ERX vs TQQQ/ERX comparison already showed; ^NDX is
        the faithful proxy for what TQQQ itself tracks.

    ERX (2x energy) pre-2008-11-19:
        2x-daily-compounded [Fama-French Enrgy (pre-1998) chained with
        real XLE (1998-2008)] -- reusing the exact same proxy chain
        already built for the unlevered Extended variant, since XLE
        genuinely is what ERX tracks (unlike TQQQ/XLK).

Neither synthetic-leverage segment includes the expense ratio / daily
financing cost real leveraged ETFs carry -- so the pre-inception synthetic
portions are a mild optimistic upper bound relative to what an actual fund
would have delivered, on top of the volatility-decay effects that ARE
captured by daily compounding. XLU and XLP+IEF are unchanged from the
unlevered Extended variant (Fama-French Utils/NoDur + DGS10 bond proxy +
real, as already built).

Usage: .venv/Scripts/python.exe backtest/simulate_extended_levered_monthly.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_monthly import (
    FF_PROXY,
    load_dgs10_bond_proxy,
    load_ff_proxy,
    load_real_total_return,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")

TQQQ_LEVERAGE = 3
ERX_LEVERAGE = 2


def spliced_leveraged_series(
    con: duckdb.DuckDBPyConnection,
    levered_ticker: str,
    unlevered_proxy: pd.Series,
    leverage: int,
) -> pd.Series:
    real = load_real_total_return(con, levered_ticker)
    inception = real.index.min()
    synthetic = (leverage * unlevered_proxy[unlevered_proxy.index < inception]).rename(levered_ticker)
    return pd.concat([synthetic, real]).sort_index()


def build_tqqq_extended(con: duckdb.DuckDBPyConnection) -> pd.Series:
    ndx = load_real_total_return(con, "^NDX")  # price return only, no dividends on an index -- fine, matches ^GSPC treatment
    return spliced_leveraged_series(con, "TQQQ", ndx, TQQQ_LEVERAGE)


def build_erx_extended(con: duckdb.DuckDBPyConnection) -> pd.Series:
    ff_enrgy = load_ff_proxy(con, FF_PROXY["XLE"])
    real_xle = load_real_total_return(con, "XLE")
    xle_chain = pd.concat([ff_enrgy[ff_enrgy.index < real_xle.index.min()], real_xle]).sort_index()
    return spliced_leveraged_series(con, "ERX", xle_chain, ERX_LEVERAGE)


def spliced_series_unlevered(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    real = load_real_total_return(con, ticker)
    inception = real.index.min()
    if ticker == "IEF":
        proxy = load_dgs10_bond_proxy(con)
    else:
        proxy = load_ff_proxy(con, FF_PROXY[ticker])
    return pd.concat([proxy[proxy.index < inception], real]).sort_index()


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
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

    print(f"Extended, Levered (TQQQ/ERX) -- Monthly: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Extended, Levered (TQQQ/ERX)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "extended_levered_tqqq_erx_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
