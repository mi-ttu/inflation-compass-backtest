"""Inflation Compass -- Extended (1990+): backtest execution for
regime_history_extended (transform/build_signals_extended.py), using
proxy daily returns for each traded holding before its real inception:

    XLE  -> Fama-French Enrgy (pre-1998-12-22)
    XLK  -> Fama-French BusEq (pre-1998-12-22)
    XLU  -> Fama-French Utils (pre-1998-12-22)
    XLP  -> Fama-French NoDur (pre-1998-12-22)
    IEF  -> synthetic bond total return from DGS10 (pre-2002-07-30),
            using the standard yield-approximation formula:
                daily_return ~= y[t-1]/252 - D_mod * (y[t] - y[t-1])
            with D_mod = 7.5 (IEF's approximate modified duration for a
            7-10yr Treasury note fund). This is a real approximation, not
            actual historical bond fund returns -- flagged explicitly.
    SPY  -> ^GSPC (price return, throughout) -- used only as the passive
            benchmark. This slightly understates true total return for
            1990-1993 specifically (SPY's ~2-3%/yr dividend yield isn't
            captured before SPY itself existed), a minor, bounded gap.

Reported results are restricted to 1990-01-01 onward (matching
AllocateSmartly's stated backtest start) -- 1988-1989 in the underlying
tables is warmup only, needed for the 200-day SMA and other rolling
windows to be valid by 1990.

Usage: .venv/Scripts/python.exe backtest/simulate_extended_monthly.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from _levered_common import perf_stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")

FF_PROXY = {"XLE": "Enrgy", "XLK": "BusEq", "XLU": "Utils", "XLP": "NoDur"}
IEF_DURATION = 7.5


def load_real_total_return(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    df = con.execute(
        "SELECT trading_date, daily_total_return FROM total_return_index WHERE ticker = ? ORDER BY trading_date",
        [ticker],
    ).df()
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.set_index("trading_date")["daily_total_return"]


def load_ff_proxy(con: duckdb.DuckDBPyConnection, industry: str) -> pd.Series:
    df = con.execute(
        "SELECT trading_date, daily_return FROM famafrench_industry_returns WHERE industry = ? ORDER BY trading_date",
        [industry],
    ).df()
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.set_index("trading_date")["daily_return"]


def load_dgs10_bond_proxy(con: duckdb.DuckDBPyConnection) -> pd.Series:
    df = con.execute(
        "SELECT observation_date, value FROM fred_series WHERE series_id = 'DGS10' ORDER BY observation_date"
    ).df()
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    yield_pct = df.set_index("observation_date")["value"] / 100.0
    yield_change = yield_pct.diff()
    daily_return = yield_pct.shift(1) / 252.0 - IEF_DURATION * yield_change
    return daily_return


def spliced_series(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    real = load_real_total_return(con, ticker)
    inception = real.index.min()

    if ticker == "IEF":
        proxy = load_dgs10_bond_proxy(con)
    elif ticker in FF_PROXY:
        proxy = load_ff_proxy(con, FF_PROXY[ticker])
    else:
        raise ValueError(f"No proxy defined for {ticker}")

    proxy_segment = proxy[proxy.index < inception]
    return pd.concat([proxy_segment, real]).sort_index()


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    spliced = {t: spliced_series(con, t) for t in ["XLE", "XLK", "XLU", "XLP", "IEF"]}
    gspc = load_real_total_return(con, "^GSPC")

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        holding = regime.loc[i, "holding"]
        dates = pd.DatetimeIndex([d for d in gspc.index if start < d <= end])

        if holding == "XLP+IEF_5050":
            leg_xlp = (1 + spliced["XLP"].reindex(dates)).cumprod()
            leg_ief = (1 + spliced["IEF"].reindex(dates)).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = spliced[holding].reindex(dates)

        spy_ret = gspc.reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "holding": holding,
                "model_return": model_ret.loc[dt], "spy_return": spy_ret.loc[dt],
            })

    return pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    daily = build_daily_equity(con)
    con.close()

    daily = daily[daily["trading_date"] >= REPORT_START].reset_index(drop=True)

    print(f"Inflation Compass -- Extended (1990+): {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each holding:")
    print((daily["holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Extended -- Monthly (1990+)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "extended_monthly_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
