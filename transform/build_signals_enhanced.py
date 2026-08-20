"""Gold layer (Enhanced variant): parameter-diversified ("ensembled")
signal engine, per AllocateSmartly's description of David Varadi's
"Enhanced" Inflation Compass:

    "Rather than relying on a single lookback period -- for example, the
    60-day change in the breakeven rate -- the Enhanced version averages
    the signal across multiple parameter values."
    (allocatesmartly.com, "Taming the Wildcard", 2026-08-06)

Varadi's own exact ensembling algorithm isn't public. This is our own
defensible reconstruction, with the design choices stated explicitly:

- ENSEMBLE WINDOWS = {40, 60, 80} trading days -- these are exactly the
  three windows Varadi's own published robustness table tested for both
  the breakeven-momentum and asset-momentum lookbacks (all three sit on
  the "broad plateau" he reports, Sharpe 1.2-1.5 across all of them), so
  this isn't an arbitrary choice of ensemble members.
- Only the two MOMENTUM conditions are ensembled (breakeven momentum,
  asset momentum) -- these are the "lookback-sensitive" conditions
  AllocateSmartly's description is about. The growth filter (200-day SMA)
  and the breakeven level threshold (2.0%, the Fed's target) are left
  unchanged, since they're structural anchors rather than an arbitrary
  lookback choice.
- Ensembling method: compute the boolean condition at each of the three
  windows, then take a MAJORITY VOTE (mean > 0.5) rather than averaging
  the raw numeric values. This sidesteps having to reconcile different
  units (a T5YIE level difference vs. a regression slope) and keeps the
  combination logic identical in structure to the Original
  (breakeven_above_target AND (breakeven_momentum_up OR asset_momentum_up)),
  just with each sub-condition now a vote across 3 windows instead of a
  single 60-day read.
- Bootstrap: same convention as the Original (transform/build_signals.py)
  -- a momentum condition that's undefined for lack of history (the first
  ~80 trading days of T5YIE, now that 80 is the longest window) is treated
  as False for that window rather than NULL, so the ensemble vote is still
  well-defined from day one.

Usage: .venv/Scripts/python.exe transform/build_signals_enhanced.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

BREAKEVEN_TARGET = 2.0
ENSEMBLE_WINDOWS = (40, 60, 80)
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


def load_breakeven_ensemble(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    t5yie = con.execute(
        "SELECT observation_date AS trading_date, value AS t5yie FROM fred_series "
        "WHERE series_id = 'T5YIE' ORDER BY observation_date"
    ).df()
    t5yie["breakeven_above_target"] = t5yie["t5yie"] > BREAKEVEN_TARGET

    vote_cols = []
    for w in ENSEMBLE_WINDOWS:
        col = f"breakeven_momentum_up_{w}"
        t5yie[col] = (t5yie["t5yie"] > t5yie["t5yie"].shift(w)).fillna(False)
        vote_cols.append(col)

    t5yie["breakeven_momentum_up_ensemble_frac"] = t5yie[vote_cols].mean(axis=1)
    t5yie["breakeven_momentum_up_enhanced"] = t5yie["breakeven_momentum_up_ensemble_frac"] > 0.5
    return t5yie


def load_sector_basket_ensemble(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
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

    vote_cols = []
    for w in ENSEMBLE_WINDOWS:
        slope_col = f"asset_momentum_slope_{w}"
        vote_col = f"_asset_momentum_up_{w}"
        basket[slope_col] = rolling_slope(basket["sector_basket_ratio"], w)
        basket[vote_col] = (basket[slope_col] > 0).fillna(False)
        vote_cols.append(vote_col)

    basket["asset_momentum_up_ensemble_frac"] = basket[vote_cols].mean(axis=1)
    basket["asset_momentum_up_enhanced"] = basket["asset_momentum_up_ensemble_frac"] > 0.5
    return basket.drop(columns=vote_cols)


def build_signals_daily_enhanced(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    growth = load_growth(con)
    breakeven = load_breakeven_ensemble(con)
    basket = load_sector_basket_ensemble(con)

    df = growth.merge(breakeven, on="trading_date", how="inner").merge(basket, on="trading_date", how="inner")
    df["inflation_on"] = df["breakeven_above_target"] & (
        df["breakeven_momentum_up_enhanced"] | df["asset_momentum_up_enhanced"]
    )

    cols = [
        "trading_date", "spy_close", "spy_sma_200", "growth_up", "t5yie", "breakeven_above_target",
        "breakeven_momentum_up_40", "breakeven_momentum_up_60", "breakeven_momentum_up_80",
        "breakeven_momentum_up_ensemble_frac", "breakeven_momentum_up_enhanced",
        "asset_momentum_slope_40", "asset_momentum_slope_60", "asset_momentum_slope_80",
        "asset_momentum_up_ensemble_frac", "asset_momentum_up_enhanced", "inflation_on",
    ]
    return df[cols]


def build_regime_history_enhanced(signals: pd.DataFrame) -> pd.DataFrame:
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

    signals = build_signals_daily_enhanced(con)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM signals_daily_enhanced")
        con.execute(
            """
            INSERT INTO signals_daily_enhanced
                (trading_date, spy_close, spy_sma_200, growth_up, t5yie, breakeven_above_target,
                 breakeven_momentum_up_40, breakeven_momentum_up_60, breakeven_momentum_up_80,
                 breakeven_momentum_up_ensemble_frac, breakeven_momentum_up_enhanced,
                 asset_momentum_slope_40, asset_momentum_slope_60, asset_momentum_slope_80,
                 asset_momentum_up_ensemble_frac, asset_momentum_up_enhanced, inflation_on)
            SELECT trading_date, spy_close, spy_sma_200, growth_up, t5yie, breakeven_above_target,
                   breakeven_momentum_up_40, breakeven_momentum_up_60, breakeven_momentum_up_80,
                   breakeven_momentum_up_ensemble_frac, breakeven_momentum_up_enhanced,
                   asset_momentum_slope_40, asset_momentum_slope_60, asset_momentum_slope_80,
                   asset_momentum_up_ensemble_frac, asset_momentum_up_enhanced, inflation_on
            FROM signals
            """
        )

        regime = build_regime_history_enhanced(signals)
        con.execute("DELETE FROM regime_history_enhanced")
        con.execute(
            """
            INSERT INTO regime_history_enhanced (decision_date, growth_up, inflation_on, regime, holding)
            SELECT decision_date, growth_up, inflation_on, regime, holding FROM regime
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    print(f"signals_daily_enhanced: {len(signals)} rows, {signals['trading_date'].min()} -> {signals['trading_date'].max()}")
    print(f"regime_history_enhanced: {len(regime)} month-end decisions, {regime['decision_date'].min()} -> {regime['decision_date'].max()}")
    print(regime["holding"].value_counts())

    con.close()


if __name__ == "__main__":
    main()
