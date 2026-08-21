"""Walk-forward parameter-selection robustness test for the Original
(2003-2026, T5YIE-only) Unlevered strategy.

The published robustness table (and this project's own "Enhanced" ensemble
variant) checks whether NEARBY parameters also look good over the FULL
history -- that's an in-sample check: it can only tell you the chosen
parameter isn't a narrow spike, not whether picking it required hindsight.

This is the stricter test: at each walk-forward year Y, select the
momentum-window parameter (applied to both the breakeven-momentum and
asset-momentum conditions, generalizing build_signals.py's fixed
MOMENTUM_WINDOW=60) using ONLY data strictly before year Y, then apply that
selection, completely unchanged, to year Y's actual returns -- data the
selection step never saw. Rolling this forward year by year and
concatenating the results gives a genuine out-of-sample equity curve, which
is then compared against simply using the fixed, published 60-day window
the whole time.

Simplification for tractability: signal computation and the walk-forward
comparison both use MONTHLY returns (compounding total_return_index within
each held month), not the daily-NAV granularity used for this project's
official reported stats. Monthly precision is standard and sufficient for a
parameter-selection criterion; it is not used to re-report headline
performance numbers.

Usage: .venv/Scripts/python.exe backtest/walk_forward_test.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

BREAKEVEN_TARGET = 2.0
SMA_WINDOW = 200
CANDIDATE_WINDOWS = [40, 50, 60, 70, 80]
PUBLISHED_WINDOW = 60
FIRST_WALK_FORWARD_YEAR = 2013  # ~10-year initial training window (2003-2012)
LAST_YEAR = 2026
TRADING_DAYS_PER_YEAR = 252

POSITIVE_BASKET = {"XLE": 0.5, "XLI": 1 / 6, "XLF": 1 / 6, "XLB": 1 / 6}
NEGATIVE_BASKET = {"XLU": 1 / 3, "XLV": 1 / 3, "XLP": 1 / 3}
REGIME_MAP = {
    (True, True): "XLE",
    (True, False): "XLK",
    (False, True): "XLU",
    (False, False): "XLP+IEF_5050",
}


def rolling_slope(series: pd.Series, window: int) -> pd.Series:
    x = np.arange(window)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def _slope(y: np.ndarray) -> float:
        return ((x - x_mean) * (y - y.mean())).sum() / denom

    return series.rolling(window).apply(_slope, raw=True)


def load_growth(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    spy = con.execute(
        "SELECT trading_date, close FROM equity_prices WHERE ticker = 'SPY' ORDER BY trading_date"
    ).df()
    spy["spy_sma_200"] = spy["close"].rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    spy["growth_up"] = spy["close"] > spy["spy_sma_200"]
    return spy.rename(columns={"close": "spy_close"})[["trading_date", "growth_up"]]


def load_sector_basket_ratio(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    tickers = list(POSITIVE_BASKET) + list(NEGATIVE_BASKET)
    placeholders = ", ".join(["?"] * len(tickers))
    returns = con.execute(
        f"SELECT ticker, trading_date, daily_total_return FROM total_return_index WHERE ticker IN ({placeholders}) ORDER BY trading_date",
        tickers,
    ).df()
    wide = returns.pivot(index="trading_date", columns="ticker", values="daily_total_return").dropna()
    pos_return = sum(wide[t] * w for t, w in POSITIVE_BASKET.items())
    neg_return = sum(wide[t] * w for t, w in NEGATIVE_BASKET.items())
    ratio = (1.0 + pos_return).cumprod() / (1.0 + neg_return).cumprod()
    return pd.DataFrame({"trading_date": wide.index, "sector_basket_ratio": ratio.values})


def regime_history_for_window(growth: pd.DataFrame, breakeven: pd.DataFrame, basket: pd.DataFrame, window: int) -> pd.DataFrame:
    bk = breakeven.copy()
    bk["t5yie_ago"] = bk["t5yie"].shift(window)
    bk["breakeven_momentum_up"] = bk["t5yie"] > bk["t5yie_ago"]
    bk["breakeven_above_target"] = bk["t5yie"] > BREAKEVEN_TARGET

    bsk = basket.copy()
    bsk["slope"] = rolling_slope(bsk["sector_basket_ratio"], window)
    bsk["asset_momentum_up"] = bsk["slope"] > 0

    df = growth.merge(bk, on="trading_date", how="inner").merge(bsk, on="trading_date", how="inner")
    breakeven_momentum_filled = df["breakeven_momentum_up"].fillna(False)
    df["inflation_on"] = df["breakeven_above_target"] & (breakeven_momentum_filled | df["asset_momentum_up"])

    valid = df.dropna(subset=["growth_up", "inflation_on"]).copy()
    valid["year_month"] = valid["trading_date"].dt.to_period("M")
    month_end = valid.groupby("year_month")["trading_date"].max().reset_index()
    regime_rows = valid.merge(month_end, on=["year_month", "trading_date"])
    regime_rows["holding"] = [
        REGIME_MAP[(bool(g), bool(i))] for g, i in zip(regime_rows["growth_up"], regime_rows["inflation_on"], strict=True)
    ]
    return regime_rows[["trading_date", "holding"]].rename(columns={"trading_date": "decision_date"}).reset_index(drop=True)


def monthly_returns_for_regime(con: duckdb.DuckDBPyConnection, regime: pd.DataFrame) -> pd.DataFrame:
    tickers = ["XLE", "XLK", "XLU", "XLP", "IEF"]
    tri = {}
    for t in tickers:
        df = con.execute(
            "SELECT trading_date, daily_total_return FROM total_return_index WHERE ticker = ? ORDER BY trading_date", [t]
        ).df()
        df["trading_date"] = pd.to_datetime(df["trading_date"])
        tri[t] = (1 + df.set_index("trading_date")["daily_total_return"]).cumprod()

    rows = []
    for i in range(len(regime) - 1):
        start, end, holding = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"], regime.loc[i, "holding"]
        if holding == "XLP+IEF_5050":
            r = 0.5 * (tri["XLP"].loc[end] / tri["XLP"].loc[start] - 1) + 0.5 * (tri["IEF"].loc[end] / tri["IEF"].loc[start] - 1)
        else:
            r = tri[holding].loc[end] / tri[holding].loc[start] - 1
        rows.append({"period_end": end, "return": r})
    return pd.DataFrame(rows)


def sharpe_monthly(returns: pd.Series) -> float:
    if len(returns) < 2 or returns.std(ddof=1) == 0:
        return np.nan
    return (returns.mean() * 12) / (returns.std(ddof=1) * np.sqrt(12))


def cagr_monthly(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    n_years = len(returns) / 12
    return equity.iloc[-1] ** (1 / n_years) - 1 if n_years > 0 else np.nan


def maxdd_monthly(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    return (equity / equity.cummax() - 1).min()


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    growth = load_growth(con)
    breakeven = con.execute(
        "SELECT observation_date AS trading_date, value AS t5yie FROM fred_series WHERE series_id = 'T5YIE' ORDER BY observation_date"
    ).df()
    basket = load_sector_basket_ratio(con)

    print(f"Computing regime history + monthly returns for candidate windows {CANDIDATE_WINDOWS}...")
    monthly_by_window: dict[int, pd.DataFrame] = {}
    for w in CANDIDATE_WINDOWS:
        regime = regime_history_for_window(growth, breakeven, basket, w)
        monthly_by_window[w] = monthly_returns_for_regime(con, regime).set_index("period_end")["return"]
    con.close()
    print("Done.\n")

    fixed_returns = monthly_by_window[PUBLISHED_WINDOW]

    walk_forward_rows = []
    selections = []
    for year in range(FIRST_WALK_FORWARD_YEAR, LAST_YEAR + 1):
        train_cutoff = pd.Timestamp(f"{year}-01-01")
        best_window, best_sharpe = None, -np.inf
        for w, series in monthly_by_window.items():
            train = series[series.index < train_cutoff]
            s = sharpe_monthly(train)
            if pd.notna(s) and s > best_sharpe:
                best_window, best_sharpe = w, s
        selections.append({"year": year, "selected_window": best_window, "training_sharpe": best_sharpe})

        test_series = monthly_by_window[best_window]
        test_year = test_series[(test_series.index >= pd.Timestamp(f"{year}-01-01")) & (test_series.index < pd.Timestamp(f"{year + 1}-01-01"))]
        for dt, r in test_year.items():
            walk_forward_rows.append({"period_end": dt, "return": r})

    wf_df = pd.DataFrame(walk_forward_rows).set_index("period_end")["return"].sort_index()
    sel_df = pd.DataFrame(selections)

    test_start = pd.Timestamp(f"{FIRST_WALK_FORWARD_YEAR}-01-01")
    fixed_test = fixed_returns[fixed_returns.index >= test_start]

    print("Parameter selected each walk-forward year (using only data before that year):")
    print(sel_df.to_string(index=False))
    print()

    print(f"Walk-forward OOS result ({FIRST_WALK_FORWARD_YEAR}-{LAST_YEAR}, re-selected annually) "
          f"vs. fixed {PUBLISHED_WINDOW}-day window over the SAME period:")
    for name, series in [("Walk-forward (re-selected annually)", wf_df), (f"Fixed {PUBLISHED_WINDOW}-day (published)", fixed_test)]:
        print(f"  {name}: CAGR {cagr_monthly(series):.2%}  Sharpe {sharpe_monthly(series):.2f}  MaxDD {maxdd_monthly(series):.1%}  "
              f"Growth of $1 {(1 + series).prod():.2f}  ({len(series)} months)")

    out_dir = PROJECT_ROOT / "backtest"
    sel_df.to_csv(out_dir / "walk_forward_selections.csv", index=False)
    wf_df.to_csv(out_dir / "walk_forward_returns.csv")
    print(f"\nSaved selections and walk-forward returns to {out_dir}")


if __name__ == "__main__":
    main()
