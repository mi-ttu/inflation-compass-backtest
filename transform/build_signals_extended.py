"""Gold layer (Extended variant): a 1990+ reconstruction of the Original
Inflation Compass, replicating what AllocateSmartly describes doing --
extending the backtest with "a decade-plus of additional data," with
everything before 2003 explicitly out-of-sample for the Original model
(the real T5YIE breakeven series doesn't exist before 2003-01-02).

Three genuine substitutions, each documented with its rationale:

1. GROWTH FILTER: ^GSPC (the S&P 500 index itself, free via Yahoo back to
   1927) replaces SPY throughout the ENTIRE 1990-2026 range -- not just
   pre-2003. SPY tracks the index almost exactly, so using one continuous
   series avoids an unnecessary splice for a condition that barely needs
   one.

2. INFLATION LEVEL/MOMENTUM: a genuine methodology splice at 2003-01-02.
   Before that date, T5YIE doesn't exist, so we substitute EXPINF5YR (the
   Cleveland Fed's model-based 5-year expected inflation estimate, free
   via FRED, monthly, back to 1982) against the same 2.0% Fed-target
   threshold. Because EXPINF5YR is monthly, "60 trading days" doesn't
   translate -- we use a 3-CALENDAR-MONTH change as the pre-2003 momentum
   proxy instead. From 2003-01-02 onward, the real T5YIE / 60-trading-day
   signal (already built in transform/build_signals.py) is used
   unchanged. These are two different measurements of a similar concept,
   not a smooth transition -- that's an unavoidable limitation of the
   pre-2003 segment, not a modeling choice.

3. SECTOR-BASKET ASSET MOMENTUM: before the SPDR sector ETFs existed
   (Dec 1998), we substitute Fama-French 12 Industry Portfolio daily
   returns (free, Ken French's Data Library, back to 1926), mapped to the
   same positive/negative basket structure:

       XLE -> Enrgy   (exact match)
       XLI -> Manuf   (closest available: general manufacturing)
       XLF -> Money   (Finance -- exact match)
       XLB -> Chems   (closest available: chemicals, not full materials)
       XLU -> Utils   (exact match)
       XLV -> Hlth    (exact match)
       XLP -> NoDur   (closest available: consumer nondurables)

   Unlike the inflation splice, this one CAN be made continuous: the
   sector-basket ratio is a cumulative-growth ratio, so instead of
   independently rebasing the pre-1998 (Fama-French) and post-1998 (SPDR)
   segments to 1.0 each, we chain them -- the SPDR-based segment
   continues multiplicatively from wherever the Fama-French-based segment
   left off, the same way you'd splice a total-return index across a data
   vendor switch. That keeps the 60-day rolling slope well-defined even
   for windows straddling the splice date, since it's reading one
   genuinely continuous series, not two rebased ones glued together.

Usage: .venv/Scripts/python.exe transform/build_signals_extended.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

BREAKEVEN_TARGET = 2.0
MOMENTUM_WINDOW_DAYS = 60          # T5YIE era (trading days)
MOMENTUM_WINDOW_MONTHS = 3         # EXPINF5YR era (calendar months)
SMA_WINDOW = 200
SPLICE_DATE = pd.Timestamp("2003-01-02")

# SPDR sector -> Fama-French 12-industry proxy (pre-1998-12-22)
FF_PROXY = {"XLE": "Enrgy", "XLI": "Manuf", "XLF": "Money", "XLB": "Chems",
            "XLU": "Utils", "XLV": "Hlth", "XLP": "NoDur"}
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
    gspc = con.execute(
        "SELECT trading_date, close FROM equity_prices WHERE ticker = '^GSPC' ORDER BY trading_date"
    ).df()
    gspc["trading_date"] = pd.to_datetime(gspc["trading_date"])
    gspc["spy_sma_200"] = gspc["close"].rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    gspc["growth_up"] = gspc["close"] > gspc["spy_sma_200"]
    return gspc.rename(columns={"close": "spy_close"})[["trading_date", "spy_close", "spy_sma_200", "growth_up"]]


def load_inflation_spliced(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Pre-2003 segment: EXPINF5YR, forward-filled onto the trading calendar,
    # with a 3-calendar-month momentum lookback (the monthly-appropriate
    # analog of T5YIE's 60-trading-day lookback).
    expinf = con.execute(
        "SELECT observation_date AS trading_date, value FROM fred_series "
        "WHERE series_id = 'EXPINF5YR' AND observation_date < ? ORDER BY observation_date",
        [SPLICE_DATE.date()],
    ).df()
    expinf["trading_date"] = pd.to_datetime(expinf["trading_date"])
    lookback_date = expinf["trading_date"] - pd.DateOffset(months=MOMENTUM_WINDOW_MONTHS)
    raw_monthly = con.execute(
        "SELECT observation_date, value FROM fred_series WHERE series_id = 'EXPINF5YR' ORDER BY observation_date"
    ).df()
    raw_monthly["observation_date"] = pd.to_datetime(raw_monthly["observation_date"])
    value_3mo_ago = pd.merge_asof(
        pd.DataFrame({"lookback_date": lookback_date}).sort_values("lookback_date"),
        raw_monthly.rename(columns={"observation_date": "lookback_date"}),
        on="lookback_date",
        direction="backward",
    )["value"]
    expinf = expinf.sort_values("trading_date").reset_index(drop=True)
    expinf["value_lookback"] = value_3mo_ago.reset_index(drop=True)
    expinf["inflation_signal_source"] = "EXPINF5YR_proxy"

    # Post-2003 segment: real T5YIE, 60-trading-day lookback (matches Original).
    t5yie = con.execute(
        "SELECT observation_date AS trading_date, value FROM fred_series "
        "WHERE series_id = 'T5YIE' AND observation_date >= ? ORDER BY observation_date",
        [SPLICE_DATE.date()],
    ).df()
    t5yie["trading_date"] = pd.to_datetime(t5yie["trading_date"])
    t5yie["value_lookback"] = t5yie["value"].shift(MOMENTUM_WINDOW_DAYS)
    t5yie["inflation_signal_source"] = "T5YIE"

    combined = pd.concat([expinf, t5yie], ignore_index=True).sort_values("trading_date").reset_index(drop=True)
    combined = combined.rename(columns={"value": "inflation_level"})
    combined["breakeven_above_target"] = combined["inflation_level"] > BREAKEVEN_TARGET
    combined["breakeven_momentum_up"] = (combined["inflation_level"] > combined["value_lookback"]).fillna(False)
    return combined[["trading_date", "inflation_signal_source", "inflation_level",
                      "breakeven_above_target", "breakeven_momentum_up"]]


def load_sector_basket_spliced(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Pre-1998-12-22 segment: Fama-French 12-industry proxy returns.
    ff_tickers = list(FF_PROXY.values())
    placeholders = ", ".join(["?"] * len(ff_tickers))
    ff = con.execute(
        f"""
        SELECT industry, trading_date, daily_return FROM famafrench_industry_returns
        WHERE industry IN ({placeholders}) ORDER BY trading_date
        """,
        ff_tickers,
    ).df()
    ff["trading_date"] = pd.to_datetime(ff["trading_date"])
    ff_wide = ff.pivot(index="trading_date", columns="industry", values="daily_return").dropna()
    ff_wide = ff_wide.rename(columns={v: k for k, v in FF_PROXY.items()})  # back to XLE/XLI/... names

    spdr_inception = con.execute(
        "SELECT MIN(trading_date) FROM equity_prices WHERE ticker = 'XLE'"
    ).fetchone()[0]
    ff_wide = ff_wide[ff_wide.index < pd.Timestamp(spdr_inception)]

    # Post-1998-12-22 segment: real SPDR total returns (already computed).
    spdr_tickers = list(POSITIVE_BASKET) + list(NEGATIVE_BASKET)
    placeholders = ", ".join(["?"] * len(spdr_tickers))
    spdr = con.execute(
        f"""
        SELECT ticker, trading_date, daily_total_return FROM total_return_index
        WHERE ticker IN ({placeholders}) ORDER BY trading_date
        """,
        spdr_tickers,
    ).df()
    spdr["trading_date"] = pd.to_datetime(spdr["trading_date"])
    spdr_wide = spdr.pivot(index="trading_date", columns="ticker", values="daily_total_return").dropna()

    def _basket_returns(wide: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        pos = sum(wide[t] * w for t, w in POSITIVE_BASKET.items())
        neg = sum(wide[t] * w for t, w in NEGATIVE_BASKET.items())
        return pos, neg

    pos_pre, neg_pre = _basket_returns(ff_wide)
    pos_post, neg_post = _basket_returns(spdr_wide)
    pos_return = pd.concat([pos_pre, pos_post]).sort_index()
    neg_return = pd.concat([neg_pre, neg_post]).sort_index()

    # Chain (not independently rebase) across the splice: one continuous
    # cumulative-growth series so a 60-day slope straddling the boundary
    # is reading genuinely comparable values.
    pos_cum = (1.0 + pos_return).cumprod()
    neg_cum = (1.0 + neg_return).cumprod()
    ratio = pos_cum / neg_cum

    basket = pd.DataFrame({"trading_date": ratio.index, "sector_basket_ratio": ratio.values})
    basket["sector_basket_slope_60d"] = rolling_slope(basket["sector_basket_ratio"], MOMENTUM_WINDOW_DAYS)
    basket["asset_momentum_up"] = basket["sector_basket_slope_60d"] > 0
    return basket


def build_signals_daily_extended(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    growth = load_growth(con)
    inflation = load_inflation_spliced(con)
    basket = load_sector_basket_spliced(con)

    df = growth.merge(inflation, on="trading_date", how="inner").merge(basket, on="trading_date", how="inner")
    df["inflation_on"] = df["breakeven_above_target"] & (df["breakeven_momentum_up"] | df["asset_momentum_up"])

    cols = [
        "trading_date", "spy_close", "spy_sma_200", "growth_up",
        "inflation_signal_source", "inflation_level", "breakeven_above_target", "breakeven_momentum_up",
        "sector_basket_ratio", "sector_basket_slope_60d", "asset_momentum_up", "inflation_on",
    ]
    return df[cols]


def build_regime_history_extended(signals: pd.DataFrame) -> pd.DataFrame:
    valid = signals.dropna(subset=["growth_up", "inflation_on"]).copy()
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

    signals = build_signals_daily_extended(con)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM signals_daily_extended")
        con.execute(
            """
            INSERT INTO signals_daily_extended
                (trading_date, spy_close, spy_sma_200, growth_up, inflation_signal_source, inflation_level,
                 breakeven_above_target, breakeven_momentum_up, sector_basket_ratio, sector_basket_slope_60d,
                 asset_momentum_up, inflation_on)
            SELECT trading_date, spy_close, spy_sma_200, growth_up, inflation_signal_source, inflation_level,
                   breakeven_above_target, breakeven_momentum_up, sector_basket_ratio, sector_basket_slope_60d,
                   asset_momentum_up, inflation_on
            FROM signals
            """
        )

        regime = build_regime_history_extended(signals)
        con.execute("DELETE FROM regime_history_extended")
        con.execute(
            """
            INSERT INTO regime_history_extended (decision_date, growth_up, inflation_on, regime, holding)
            SELECT decision_date, growth_up, inflation_on, regime, holding FROM regime
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    print(f"signals_daily_extended: {len(signals)} rows, {signals['trading_date'].min()} -> {signals['trading_date'].max()}")
    print(f"regime_history_extended: {len(regime)} month-end decisions, {regime['decision_date'].min()} -> {regime['decision_date'].max()}")
    print(regime["holding"].value_counts())
    print()
    print("Rows by inflation-signal source:")
    print(signals["inflation_signal_source"].value_counts())

    con.close()


if __name__ == "__main__":
    main()
