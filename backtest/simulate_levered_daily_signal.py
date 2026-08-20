"""Levered Compass -- Daily: the Daily Signal Compass cadence (signals
re-evaluated every trading day, rebalanced on any regime change, same
1-day implementation lag) combined with the same TECL-for-XLK /
ERX-for-XLE substitution used in simulate_levered_monthly.py.

Signal engine unchanged (drives off unleveraged SPY/XLE/XLK/XLI/XLF/XLB/
XLU/XLV/XLP, see transform/build_signals.py); only the traded instrument
in the two up-growth regimes changes. Restricted to TECL/ERX's shared
inception window (from simulate_levered_monthly.py: 2008-12-30 onward).

Usage: .venv/Scripts/python.exe backtest/simulate_levered_daily_signal.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
TRADING_DAYS_PER_YEAR = 252

HOLDING_SUBSTITUTION = {"XLE": "ERX", "XLK": "TECL"}
REGIME_MAP = {
    (True, True): "reflation",
    (True, False): "goldilocks",
    (False, True): "stagflation",
    (False, False): "disinflationary_slowdown",
}
HOLDING_MAP = {
    "reflation": "XLE",
    "goldilocks": "XLK",
    "stagflation": "XLU",
    "disinflationary_slowdown": "XLP+IEF_5050",
}


def load_daily_returns(con: duckdb.DuckDBPyConnection, tickers: list[str]) -> dict[str, pd.Series]:
    out = {}
    for ticker in tickers:
        df = con.execute(
            "SELECT trading_date, daily_total_return FROM total_return_index "
            "WHERE ticker = ? ORDER BY trading_date",
            [ticker],
        ).df()
        df["trading_date"] = pd.to_datetime(df["trading_date"])
        out[ticker] = df.set_index("trading_date")["daily_total_return"]
    return out


def inception_date(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Timestamp:
    row = con.execute(
        "SELECT MIN(trading_date) FROM total_return_index WHERE ticker = ?", [ticker]
    ).fetchone()
    return pd.Timestamp(row[0])


def build_daily_exposure(con: duckdb.DuckDBPyConnection, backtest_start: pd.Timestamp) -> pd.DataFrame:
    signals = con.execute(
        "SELECT trading_date, growth_up, inflation_on FROM signals_daily ORDER BY trading_date"
    ).df()
    signals["trading_date"] = pd.to_datetime(signals["trading_date"])
    signals["regime"] = [
        REGIME_MAP[(bool(g), bool(i))]
        for g, i in zip(signals["growth_up"], signals["inflation_on"], strict=True)
    ]
    signals["original_holding"] = signals["regime"].map(HOLDING_MAP)
    signals["traded_holding"] = signals["original_holding"].map(
        lambda h: HOLDING_SUBSTITUTION.get(h, h)
    )

    signals["exposure_holding"] = signals["traded_holding"].shift(1)
    signals = signals.dropna(subset=["exposure_holding"]).reset_index(drop=True)
    return signals[signals["trading_date"] >= backtest_start].reset_index(drop=True)


def simulate(con: duckdb.DuckDBPyConnection, backtest_start: pd.Timestamp) -> pd.DataFrame:
    exposure = build_daily_exposure(con, backtest_start)
    tri = load_daily_returns(con, ["ERX", "TECL", "XLU", "XLP", "IEF", "SPY"])

    exposure["run_id"] = (
        exposure["exposure_holding"] != exposure["exposure_holding"].shift(1)
    ).cumsum()

    rows = []
    for _, grp in exposure.groupby("run_id"):
        holding = grp["exposure_holding"].iloc[0]
        dates = pd.DatetimeIndex(grp["trading_date"])

        if holding == "XLP+IEF_5050":
            leg_xlp = (1.0 + tri["XLP"].reindex(dates)).cumprod()
            leg_ief = (1.0 + tri["IEF"].reindex(dates)).cumprod()
            nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = nav / nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = tri[holding].reindex(dates)

        spy_ret = tri["SPY"].reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "traded_holding": holding,
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


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    backtest_start = max(inception_date(con, "TECL"), inception_date(con, "ERX"))
    daily = simulate(con, backtest_start)
    con.close()

    n_switches = int((daily["traded_holding"] != daily["traded_holding"].shift(1)).sum())
    n_days = len(daily)
    print(f"Levered Compass -- Daily: {n_days} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print(f"Holding changes (trades): {n_switches}  ({n_switches / (n_days / TRADING_DAYS_PER_YEAR):.1f} per year)")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / n_days * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"])
    spy_stats = perf_stats(daily["spy_return"])
    stats_df = pd.DataFrame({"Levered Compass -- Daily": model_stats, "S&P 500 (SPY)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "levered_daily_signal_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
