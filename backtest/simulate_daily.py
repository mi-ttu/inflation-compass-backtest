"""Daily-granularity version of the backtest, for drawdown/vol/Sharpe
stats that shouldn't be computed on monthly-sampled data (a monthly
equity curve can only register a new low at a month boundary and will
miss sharper intra-month troughs).

Same holding-period convention as simulate.py: the regime decided at
month-end t is held from t (exclusive) through t+1 (inclusive). Within
a holding period, daily NAV is built from each ticker's own daily total
return; the 50/50 XLP+IEF quadrant is NOT rebalanced intra-month (two
sub-positions, each starting at 0.5 of NAV at the start of the period,
left to drift until the next month-end decision, which is the standard
assumption absent an explicit stated rebalancing rule).

Usage: .venv/Scripts/python.exe backtest/simulate_daily.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
TRADING_DAYS_PER_YEAR = 252


def load_daily_returns(con: duckdb.DuckDBPyConnection, tickers: list[str]) -> pd.DataFrame:
    placeholders = ", ".join(["?"] * len(tickers))
    df = con.execute(
        f"""
        SELECT ticker, trading_date, daily_total_return
        FROM total_return_index
        WHERE ticker IN ({placeholders})
        ORDER BY trading_date
        """,
        tickers,
    ).df()
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.pivot(index="trading_date", columns="ticker", values="daily_total_return")


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    tickers = ["XLE", "XLK", "XLU", "XLP", "IEF", "SPY"]
    daily_ret = load_daily_returns(con, tickers)

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        holding = regime.loc[i, "holding"]
        window = daily_ret.loc[(daily_ret.index > start) & (daily_ret.index <= end)]

        if holding == "XLP+IEF_5050":
            leg_xlp = (1 + window["XLP"]).cumprod()
            leg_ief = (1 + window["IEF"]).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = window[holding]

        for dt, r in model_ret.items():
            rows.append({"trading_date": dt, "model_return": r, "spy_return": window.loc[dt, "SPY"]})

    return pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)


def perf_stats(returns: pd.Series) -> dict:
    equity = (1.0 + returns).cumprod()
    n_years = len(returns) / TRADING_DAYS_PER_YEAR
    cagr = equity.iloc[-1] ** (1 / n_years) - 1.0

    vol = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    ann_return = returns.mean() * TRADING_DAYS_PER_YEAR
    sharpe = ann_return / vol if vol else np.nan

    downside = returns[returns < 0]
    downside_dev = downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(downside) else np.nan
    sortino = ann_return / downside_dev if downside_dev else np.nan

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_dd = drawdown.min()
    max_dd_date = drawdown.idxmin()
    calmar = cagr / abs(max_dd) if max_dd else np.nan

    return {
        "CAGR": cagr, "Sharpe": sharpe, "Volatility": vol,
        "MaxDrawdown": max_dd, "MaxDrawdownDate": max_dd_date,
        "Sortino": sortino, "Calmar": calmar, "GrowthOf1": equity.iloc[-1],
    }


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    daily = build_daily_equity(con)
    con.close()

    print(f"Daily equity curve: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()

    model_stats = perf_stats(daily["model_return"])
    spy_stats = perf_stats(daily["spy_return"])

    stats_df = pd.DataFrame({"Inflation Compass (daily)": model_stats, "S&P 500 (daily)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "daily_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved daily returns to {out_path}")


if __name__ == "__main__":
    main()
