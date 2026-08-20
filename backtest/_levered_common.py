"""Shared simulation logic for Levered Compass -- Monthly variants.

Signal engine is always untouched (regime_history, driven by unleveraged
SPY/XLE/XLK/basket series -- see transform/build_signals.py). Only the
traded instrument in the up-growth regimes changes, per a caller-supplied
HOLDING_SUBSTITUTION mapping (e.g. {"XLE": "ERX", "XLK": "TQQQ"}).
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
TRADING_DAYS_PER_YEAR = 252


def load_total_return(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    df = con.execute(
        "SELECT trading_date, daily_total_return FROM total_return_index "
        "WHERE ticker = ? ORDER BY trading_date",
        [ticker],
    ).df()
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    return df.set_index("trading_date")["daily_total_return"]


def inception_date(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Timestamp:
    row = con.execute(
        "SELECT MIN(trading_date) FROM total_return_index WHERE ticker = ?", [ticker]
    ).fetchone()
    return pd.Timestamp(row[0])


def build_daily_equity(
    con: duckdb.DuckDBPyConnection,
    backtest_start: pd.Timestamp,
    holding_substitution: dict[str, str],
) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])
    regime = regime[regime["decision_date"] >= backtest_start].reset_index(drop=True)

    traded_tickers = {holding_substitution.get(h, h) for h in regime["holding"].unique()}
    traded_tickers |= {"XLP", "IEF", "SPY"}  # always needed for the defensive quadrant + benchmark
    daily_ret = {t: load_total_return(con, t) for t in traded_tickers}

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        original_holding = regime.loc[i, "holding"]
        traded_holding = holding_substitution.get(original_holding, original_holding)

        dates = pd.DatetimeIndex([d for d in daily_ret["SPY"].index if start < d <= end])

        if traded_holding == "XLP+IEF_5050":
            leg_xlp = (1 + daily_ret["XLP"].reindex(dates)).cumprod()
            leg_ief = (1 + daily_ret["IEF"].reindex(dates)).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = daily_ret[traded_holding].reindex(dates)

        spy_ret = daily_ret["SPY"].reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "original_holding": original_holding,
                "traded_holding": traded_holding,
                "model_return": model_ret.loc[dt], "spy_return": spy_ret.loc[dt],
            })

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
    calmar = cagr / abs(max_dd) if max_dd else np.nan
    return {
        "CAGR": cagr, "Sharpe": sharpe, "Volatility": vol,
        "MaxDrawdown": max_dd, "Sortino": sortino, "Calmar": calmar,
        "GrowthOf1": equity.iloc[-1],
    }


def run_variant(strategy_name: str, holding_substitution: dict[str, str], output_filename: str) -> None:
    con = duckdb.connect(str(DB_PATH))
    starts = {t: inception_date(con, t) for t in holding_substitution.values()}
    backtest_start = max(starts.values())
    print(f"{strategy_name}")
    for ticker, start in starts.items():
        print(f"  {ticker} inception: {start.date()}")
    print(f"  Backtest window starts: {backtest_start.date()} (latest inception among substituted tickers)")
    print()

    daily = build_daily_equity(con, backtest_start, holding_substitution)
    con.close()

    print(f"{len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"])
    spy_stats = perf_stats(daily["spy_return"])
    stats_df = pd.DataFrame({strategy_name: model_stats, "S&P 500 (SPY)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / output_filename
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")
