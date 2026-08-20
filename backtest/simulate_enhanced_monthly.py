"""Enhanced Inflation Compass -- Monthly: same month-end decision cadence
and same traded instruments (XLE/XLK/XLU/XLP+IEF, unlevered) as the
Original monthly model, but driven by regime_history_enhanced --
built from transform/build_signals_enhanced.py's parameter-diversified
("ensembled") momentum conditions instead of a single 60-day lookback.

Same daily-NAV-within-a-monthly-holding-period methodology as
backtest/simulate_daily.py, for a fair, granularity-matched comparison
against the Original.

Usage: .venv/Scripts/python.exe backtest/simulate_enhanced_monthly.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"


def load_total_return(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    df = con.execute(
        "SELECT trading_date, daily_total_return FROM total_return_index WHERE ticker = ? ORDER BY trading_date",
        [ticker],
    ).df()
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.set_index("trading_date")["daily_total_return"]


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_enhanced ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    tickers = ["XLE", "XLK", "XLU", "XLP", "IEF", "SPY"]
    daily_ret = {t: load_total_return(con, t) for t in tickers}

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        holding = regime.loc[i, "holding"]
        dates = pd.DatetimeIndex([d for d in daily_ret["SPY"].index if start < d <= end])

        if holding == "XLP+IEF_5050":
            leg_xlp = (1 + daily_ret["XLP"].reindex(dates)).cumprod()
            leg_ief = (1 + daily_ret["IEF"].reindex(dates)).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = daily_ret[holding].reindex(dates)

        spy_ret = daily_ret["SPY"].reindex(dates)
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

    print(f"Enhanced Inflation Compass -- Monthly: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each holding:")
    print((daily["holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Enhanced Inflation Compass -- Monthly": model_stats, "S&P 500 (SPY)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "enhanced_monthly_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
