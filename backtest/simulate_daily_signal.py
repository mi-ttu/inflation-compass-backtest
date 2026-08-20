"""Daily Signal Compass -- a daily-reactive variant of the Inflation Compass
Model.

The original model (simulate.py / simulate_daily.py) evaluates the four
signal conditions only at month-end and holds that decision for the whole
following month. This variant uses the exact same signal definitions
(signals_daily, from transform/build_signals.py -- nothing about the
indicators themselves changes) but re-evaluates them EVERY trading day and
rebalances immediately whenever the resulting regime/holding differs from
the previous day's, rather than waiting for a month boundary.

Same 1-day implementation lag as the monthly version, to avoid lookahead:
the regime decided from day t's close governs day t+1's return, i.e.
exposure[t] = holding decided using signals_daily as of t-1.

The 50/50 XLP+IEF quadrant is NOT continuously rebalanced -- each time the
strategy enters that quadrant (whether held for one day or several weeks),
the two legs start fresh at 50/50 and are left to drift until the next
holding change. Same convention as simulate_daily.py.

Usage: .venv/Scripts/python.exe backtest/simulate_daily_signal.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
TRADING_DAYS_PER_YEAR = 252

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


def build_daily_exposure(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    signals = con.execute(
        "SELECT trading_date, growth_up, inflation_on FROM signals_daily ORDER BY trading_date"
    ).df()
    signals["trading_date"] = pd.to_datetime(signals["trading_date"])
    signals["regime"] = [
        REGIME_MAP[(bool(g), bool(i))]
        for g, i in zip(signals["growth_up"], signals["inflation_on"], strict=True)
    ]
    signals["holding"] = signals["regime"].map(HOLDING_MAP)

    # 1-day implementation lag: today's exposure is the decision made from
    # yesterday's close, exactly mirroring the monthly model's "decided at
    # month-end, held next month" convention applied daily instead.
    signals["exposure_holding"] = signals["holding"].shift(1)
    signals["exposure_regime"] = signals["regime"].shift(1)
    return signals.dropna(subset=["exposure_holding"]).reset_index(drop=True)


def simulate(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    exposure = build_daily_exposure(con)
    tri = load_daily_returns(con, ["XLE", "XLK", "XLU", "XLP", "IEF", "SPY"])

    exposure["run_id"] = (
        exposure["exposure_holding"] != exposure["exposure_holding"].shift(1)
    ).cumsum()

    rows = []
    for _, grp in exposure.groupby("run_id"):
        holding = grp["exposure_holding"].iloc[0]
        regime = grp["exposure_regime"].iloc[0]
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
            rows.append(
                {
                    "trading_date": dt,
                    "regime": regime,
                    "holding": holding,
                    "model_return": model_ret.loc[dt],
                    "spy_return": spy_ret.loc[dt],
                }
            )

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


def apply_cost(returns: pd.Series, switches: pd.Series, bps_per_switch: float) -> pd.Series:
    """Deduct a round-trip cost on every day the holding actually changes."""
    cost = switches.astype(float) * (bps_per_switch / 10_000.0)
    return returns - cost


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    daily = simulate(con)
    con.close()

    n_switches = int((daily["holding"] != daily["holding"].shift(1)).sum())
    n_days = len(daily)
    print(f"Daily Signal Compass: {n_days} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print(f"Holding changes (trades): {n_switches}  ({n_switches / (n_days / TRADING_DAYS_PER_YEAR):.1f} per year)")
    print()
    print("Time in each holding:")
    print((daily["holding"].value_counts() / n_days * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"])
    spy_stats = perf_stats(daily["spy_return"])
    stats_df = pd.DataFrame({"Daily Signal Compass": model_stats, "S&P 500 (SPY)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)
    print()

    switches = daily["holding"] != daily["holding"].shift(1)
    print("Sensitivity to per-switch transaction cost (round-trip bps):")
    for bps in (0, 5, 10, 20, 50):
        costed_returns = apply_cost(daily["model_return"], switches, bps)
        s = perf_stats(costed_returns)
        print(f"  {bps:>3} bps: CAGR {s['CAGR']:.2%}, Sharpe {s['Sharpe']:.2f}, Growth of $1 = ${s['GrowthOf1']:.1f}")

    out_path = PROJECT_ROOT / "backtest" / "daily_signal_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
