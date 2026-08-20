"""Gold layer: compute the four Inflation Compass signal conditions
daily, then derive the month-end regime call and target holding.

Design decisions (documented here since they affect reproduction fidelity):

- Growth filter (SPY vs 200-day SMA) uses RAW CLOSE, not total return.
  This is the standard convention for price trend-following filters —
  the crossover is meant to reflect what a chart actually shows, not a
  dividend-adjusted series. SPY has never split, so raw close carries
  no artificial jumps.

- The sector-basket inflation indicator uses TOTAL RETURN daily returns
  for each component ETF (XLE/XLI/XLF/XLB/XLU/XLV/XLP), consistent with
  the project's total-return standard — several of these sectors carry
  meaningful yield, and yield differences between the positive and
  negative baskets would otherwise bias a pure price-return indicator.

- Bootstrap period: breakeven_momentum_up (T5YIE vs 60 trading days ago)
  is undefined for T5YIE's first ~60 trading days (from 2003-01-02),
  since there's no 60-days-ago observation yet. During that ~60-day
  window it's treated as False, so inflation_on falls back to
  asset_momentum_up alone (which has full history available, since the
  sector ETFs go back to 1998). This affects about 1% of the sample and
  is noted explicitly rather than silently defaulted.

Usage: .venv/Scripts/python.exe transform/build_signals.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

BREAKEVEN_TARGET = 2.0
MOMENTUM_WINDOW = 60
SMA_WINDOW = 200

POSITIVE_BASKET = {"XLE": 0.5, "XLI": 1 / 6, "XLF": 1 / 6, "XLB": 1 / 6}
NEGATIVE_BASKET = {"XLU": 1 / 3, "XLV": 1 / 3, "XLP": 1 / 3}

REGIME_MAP = {
    (True, True): ("reflation", "XLE"),
    (True, False): ("goldilocks", "XLK"),
    (False, True): ("stagflation", "XLU"),
    (False, False): ("disinflationary_slowdown", "XLP+IEF_5050"),
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
    return spy.rename(columns={"close": "spy_close"})[["trading_date", "spy_close", "spy_sma_200", "growth_up"]]


def load_breakeven(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    t5yie = con.execute(
        "SELECT observation_date AS trading_date, value AS t5yie FROM fred_series "
        "WHERE series_id = 'T5YIE' ORDER BY observation_date"
    ).df()
    t5yie["t5yie_60d_ago"] = t5yie["t5yie"].shift(MOMENTUM_WINDOW)
    t5yie["breakeven_momentum_up"] = t5yie["t5yie"] > t5yie["t5yie_60d_ago"]
    t5yie["breakeven_above_target"] = t5yie["t5yie"] > BREAKEVEN_TARGET
    return t5yie


def load_sector_basket(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    tickers = list(POSITIVE_BASKET) + list(NEGATIVE_BASKET)
    placeholders = ", ".join(["?"] * len(tickers))
    returns = con.execute(
        f"""
        SELECT ticker, trading_date, daily_total_return
        FROM total_return_index
        WHERE ticker IN ({placeholders})
        ORDER BY trading_date
        """,
        tickers,
    ).df()
    wide = returns.pivot(index="trading_date", columns="ticker", values="daily_total_return").dropna()

    pos_return = sum(wide[t] * w for t, w in POSITIVE_BASKET.items())
    neg_return = sum(wide[t] * w for t, w in NEGATIVE_BASKET.items())

    pos_cum = (1.0 + pos_return).cumprod()
    neg_cum = (1.0 + neg_return).cumprod()
    indicator = pos_cum / neg_cum

    basket = pd.DataFrame({"trading_date": wide.index, "sector_basket_ratio": indicator.values})
    basket["sector_basket_slope_60d"] = rolling_slope(basket["sector_basket_ratio"], MOMENTUM_WINDOW)
    basket["asset_momentum_up"] = basket["sector_basket_slope_60d"] > 0
    return basket


def build_signals_daily(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    growth = load_growth(con)
    breakeven = load_breakeven(con)
    basket = load_sector_basket(con)

    df = growth.merge(breakeven, on="trading_date", how="inner").merge(basket, on="trading_date", how="inner")

    # Bootstrap: breakeven_momentum_up is NaN for T5YIE's first 60 trading
    # days (no 60-days-ago value yet) — treat as False rather than NULL,
    # so inflation_on falls back to asset_momentum_up alone in that window.
    breakeven_momentum_filled = df["breakeven_momentum_up"].fillna(False)

    df["inflation_on"] = df["breakeven_above_target"] & (breakeven_momentum_filled | df["asset_momentum_up"])

    cols = [
        "trading_date", "spy_close", "spy_sma_200", "growth_up",
        "t5yie", "t5yie_60d_ago", "breakeven_momentum_up", "breakeven_above_target",
        "sector_basket_ratio", "sector_basket_slope_60d", "asset_momentum_up", "inflation_on",
    ]
    return df[cols].rename(columns={"t5yie": "t5yie"})


def build_regime_history(signals: pd.DataFrame, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    valid = signals.dropna(subset=["growth_up", "inflation_on"]).copy()
    valid["trading_date"] = pd.to_datetime(valid["trading_date"])
    valid["year_month"] = valid["trading_date"].dt.to_period("M")

    month_end = valid.groupby("year_month")["trading_date"].max().reset_index()
    regime_rows = valid.merge(month_end, on=["year_month", "trading_date"])

    def _map(row):
        regime, holding = REGIME_MAP[(bool(row["growth_up"]), bool(row["inflation_on"]))]
        return pd.Series({"regime": regime, "holding": holding})

    regime_rows[["regime", "holding"]] = regime_rows.apply(_map, axis=1)
    return regime_rows[["trading_date", "growth_up", "inflation_on", "regime", "holding"]].rename(
        columns={"trading_date": "decision_date"}
    )


def main() -> None:
    con = duckdb.connect(str(DB_PATH))

    signals = build_signals_daily(con)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM signals_daily")
        con.execute(
            """
            INSERT INTO signals_daily
                (trading_date, spy_close, spy_sma_200, growth_up, t5yie, t5yie_60d_ago,
                 breakeven_momentum_up, breakeven_above_target, sector_basket_ratio,
                 sector_basket_slope_60d, asset_momentum_up, inflation_on)
            SELECT trading_date, spy_close, spy_sma_200, growth_up, t5yie, t5yie_60d_ago,
                   breakeven_momentum_up, breakeven_above_target, sector_basket_ratio,
                   sector_basket_slope_60d, asset_momentum_up, inflation_on
            FROM signals
            """
        )

        regime = build_regime_history(signals, con)
        con.execute("DELETE FROM regime_history")
        con.execute(
            """
            INSERT INTO regime_history (decision_date, growth_up, inflation_on, regime, holding)
            SELECT decision_date, growth_up, inflation_on, regime, holding FROM regime
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    print(f"signals_daily: {len(signals)} rows, {signals['trading_date'].min()} -> {signals['trading_date'].max()}")
    valid_signals = signals.dropna(subset=["growth_up", "inflation_on"])
    print(f"  valid (non-null growth_up & inflation_on): {len(valid_signals)} rows from {valid_signals['trading_date'].min()}")
    print(f"regime_history: {len(regime)} month-end decisions, {regime['decision_date'].min()} -> {regime['decision_date'].max()}")
    print(regime["holding"].value_counts())

    con.close()


if __name__ == "__main__":
    main()
