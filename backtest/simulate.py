"""Simulate the Inflation Compass Model from regime_history + our own
total-return index, and compare against SPY buy-and-hold.

Holding-period convention: the regime decided at month-end t is held
from t (exclusive) through the next month-end t+1 (inclusive) — i.e.
realized return = total_return_index[t+1] / total_return_index[t] - 1.
The 50/50 XLP+IEF quadrant is rebalanced back to 50/50 at each month-end
(simple average of the two legs' monthly returns).

Risk-free rate is assumed to be 0% for Sharpe/Sortino, since the source
post doesn't specify one — noted here rather than silently assumed.

Usage: .venv/Scripts/python.exe backtest/simulate.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"


def load_total_return(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    df = con.execute(
        "SELECT trading_date, total_return_index FROM total_return_index WHERE ticker = ? ORDER BY trading_date",
        [ticker],
    ).df()
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.set_index("trading_date")["total_return_index"]


def monthly_return(tri: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    return tri.loc[end] / tri.loc[start] - 1.0


def simulate(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, regime, holding FROM regime_history ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    tri = {t: load_total_return(con, t) for t in ["XLE", "XLK", "XLU", "XLP", "IEF", "SPY"]}

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        holding = regime.loc[i, "holding"]

        if holding == "XLP+IEF_5050":
            r = 0.5 * monthly_return(tri["XLP"], start, end) + 0.5 * monthly_return(tri["IEF"], start, end)
        else:
            r = monthly_return(tri[holding], start, end)

        spy_r = monthly_return(tri["SPY"], start, end)
        rows.append({
            "period_start": start, "period_end": end,
            "holding": holding, "regime": regime.loc[i, "regime"],
            "model_return": r, "spy_return": spy_r,
        })

    return pd.DataFrame(rows)


def perf_stats(returns: pd.Series, periods_per_year: int = 12) -> dict:
    equity = (1.0 + returns).cumprod()
    n_years = len(returns) / periods_per_year
    cagr = equity.iloc[-1] ** (1 / n_years) - 1.0

    vol = returns.std() * np.sqrt(periods_per_year)
    ann_return = returns.mean() * periods_per_year
    sharpe = ann_return / vol if vol else np.nan

    downside = returns[returns < 0]
    downside_dev = downside.std() * np.sqrt(periods_per_year) if len(downside) else np.nan
    sortino = ann_return / downside_dev if downside_dev else np.nan

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd else np.nan

    return {
        "CAGR": cagr, "Sharpe": sharpe, "Volatility": vol,
        "MaxDrawdown": max_dd, "Sortino": sortino, "Calmar": calmar,
        "GrowthOf1": equity.iloc[-1],
    }


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    monthly = simulate(con)
    con.close()

    print(f"Simulated {len(monthly)} monthly periods: {monthly['period_start'].min().date()} -> {monthly['period_end'].max().date()}")
    print()

    model_stats = perf_stats(monthly["model_return"])
    spy_stats = perf_stats(monthly["spy_return"])

    stats_df = pd.DataFrame({"Inflation Compass (replication)": model_stats, "S&P 500 (SPY, replication)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)
    print()

    monthly["year"] = monthly["period_end"].dt.year
    yearly = monthly.groupby("year").apply(
        lambda g: pd.Series({
            "Inflation Compass": (1 + g["model_return"]).prod() - 1,
            "S&P 500": (1 + g["spy_return"]).prod() - 1,
        }),
        include_groups=False,
    )
    yearly["Diff"] = yearly["Inflation Compass"] - yearly["S&P 500"]
    print(yearly.map(lambda x: f"{x:+.1%}"))

    out_path = PROJECT_ROOT / "backtest" / "monthly_returns.csv"
    monthly.to_csv(out_path, index=False)
    print(f"\nSaved monthly returns to {out_path}")


if __name__ == "__main__":
    main()
