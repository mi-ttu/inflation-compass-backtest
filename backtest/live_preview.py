"""Live intraday preview: what the Hybrid (QLD/XLE), Daily variant's regime
signal would recommend for the NEXT session if today's close matched the
current (delayed) intraday quotes -- run ahead of the actual close (the
scheduled task fires at 2:30 PM Central, 30 min before it) so the daily
status email has something more current than yesterday's already-known
decision.

Reuses transform/build_signals_extended.py's own signal builders and
constants rather than re-implementing the regime logic. The only difference
from a normal backtest run: one extra synthetic "today" row built from live
quotes for ^GSPC and the seven sector ETFs (growth filter + sector-basket
momentum). The inflation inputs (T5YIE) are NOT live -- FRED publishes them
with a lag -- so today's row carries forward the latest published value.

This is a PREVIEW, not a final decision: the actual close can still move
before the session ends, and yfinance's intraday quotes are typically
delayed (not exchange-real-time).

Usage: .venv/Scripts/python.exe backtest/live_preview.py
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "transform"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_signals_extended import (  # noqa: E402
    BREAKEVEN_TARGET, MOMENTUM_WINDOW_DAYS, NEGATIVE_BASKET, POSITIVE_BASKET, REGIME_MAP, SMA_WINDOW,
    load_growth, load_inflation_spliced, load_sector_basket_spliced, rolling_slope,
)
from refresh_chart import TRADED_REGIME_MAP  # noqa: E402
# The same 2-day confirmation rule the dashboard's "Hybrid, Daily, 2-day
# confirm" series is backtested with -- reused, not reimplemented.
from simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal_confirm2 import CONFIRM_DAYS, confirmed  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

SECTORS = list(POSITIVE_BASKET) + list(NEGATIVE_BASKET)
LIVE_TICKERS = ["^GSPC", *SECTORS]
SUBSTITUTION = {"XLK": "QLD"}
HISTORY_DAYS = 63


def live_quote(ticker: str) -> float:
    """Best-effort current/delayed price for `ticker` -- fast_info first
    (a single lightweight request), falling back to the most recent
    1-minute intraday bar if that's unavailable."""
    t = yf.Ticker(ticker)
    try:
        val = t.fast_info["last_price"]
        if val:
            return float(val)
    except Exception:
        pass
    hist = t.history(period="1d", interval="1m")
    if not hist.empty:
        return float(hist["Close"].iloc[-1])
    raise RuntimeError(f"Could not get a live quote for {ticker}")


def decide(growth_up: bool, breakeven_above: bool, breakeven_mom_up: bool, asset_mom_up: bool) -> dict:
    inflation_on = breakeven_above and (breakeven_mom_up or asset_mom_up)
    _, original_holding = REGIME_MAP[(bool(growth_up), bool(inflation_on))]
    holding = SUBSTITUTION.get(original_holding, original_holding)
    return {"holding": holding, "regime": TRADED_REGIME_MAP[holding], "growthUp": bool(growth_up), "inflationOn": bool(inflation_on)}


def build_preview() -> dict:
    now_et = pd.Timestamp.now(tz="America/New_York")
    today = pd.Timestamp(now_et.date())
    session_over = now_et.hour * 60 + now_et.minute >= 16 * 60 + 15

    con = duckdb.connect(str(DB_PATH), read_only=True)
    growth = load_growth(con)
    inflation = load_inflation_spliced(con)
    basket = load_sector_basket_spliced(con)
    last_closes = {
        t: con.execute(
            "SELECT close FROM equity_prices WHERE ticker = ? AND trading_date < ? "
            "ORDER BY trading_date DESC LIMIT 1", [t, today.date()]
        ).fetchone()[0]
        for t in LIVE_TICKERS
    }
    # The calendar-aligned series is forward-filled to the newest trading day,
    # so its last date is not when FRED last published.
    inflation_as_of = con.execute(
        "SELECT MAX(observation_date) FROM fred_series WHERE series_id = 'T5YIE' AND NOT is_forward_filled"
    ).fetchone()[0]
    con.close()

    # T5YIE is published with a lag, so the newest trading days have no
    # inflation row yet -- carry the latest published value forward.
    infl_cols = ["inflation_level", "breakeven_above_target", "breakeven_momentum_up"]
    df = growth.merge(basket, on="trading_date", how="inner").merge(
        inflation[["trading_date", *infl_cols]], on="trading_date", how="left"
    ).sort_values("trading_date").reset_index(drop=True)
    df[infl_cols] = df[infl_cols].ffill()
    df = df.dropna(subset=infl_cols).reset_index(drop=True)
    df["breakeven_above_target"] = df["breakeven_above_target"].astype(bool)
    df["breakeven_momentum_up"] = df["breakeven_momentum_up"].astype(bool)
    if len(df) < 2:
        raise RuntimeError("Not enough signal history to build a preview -- run the pipeline first")

    if not session_over:
        # Mid-session, yfinance can already return today's row with the
        # delayed intraday price in the Close column -- that is not a final
        # close, so drop it and take the live-quote path below instead.
        df = df[df["trading_date"] < today].reset_index(drop=True)
    # Display only (the breakeven-momentum chart): the value 60 trading days
    # earlier. The True/False state always comes from the signal flags.
    df["breakeven_lagged"] = df["inflation_level"].shift(MOMENTUM_WINDOW_DAYS)
    has_today = df["trading_date"].iloc[-1] >= today
    last = df.iloc[-1]
    live_row = None

    if has_today:
        # The EOD pipeline already ingested a finalized close for today --
        # no live splice needed, the "preview" is today's real, final decision.
        live_prices = None
        spx, sma = float(last["spy_close"]), float(last["spy_sma_200"])
    else:
        live_prices = {t: live_quote(t) for t in LIVE_TICKERS}
        spx = live_prices["^GSPC"]
        sma = (df["spy_close"].iloc[-(SMA_WINDOW - 1):].sum() + spx) / SMA_WINDOW

        def basket_return(weights: dict) -> float:
            return sum(w * (live_prices[t] / last_closes[t] - 1.0) for t, w in weights.items())

        pos_r, neg_r = basket_return(POSITIVE_BASKET), basket_return(NEGATIVE_BASKET)
        ratios = df["sector_basket_ratio"].tolist()
        ratios.append(ratios[-1] * (1.0 + pos_r) / (1.0 + neg_r))
        slope = rolling_slope(pd.Series(ratios[-MOMENTUM_WINDOW_DAYS:]), MOMENTUM_WINDOW_DAYS).iloc[-1]

        live_row = {
            "trading_date": today, "spy_close": spx, "spy_sma_200": float(sma), "growth_up": bool(spx > sma),
            "inflation_level": float(last["inflation_level"]),
            "breakeven_above_target": bool(last["breakeven_above_target"]),
            "breakeven_momentum_up": bool(last["breakeven_momentum_up"]),
            "breakeven_lagged": float(df["inflation_level"].iloc[len(df) - MOMENTUM_WINDOW_DAYS]),
            "sector_basket_ratio": float(ratios[-1]), "sector_basket_slope_60d": float(slope),
            "asset_momentum_up": bool(slope > 0),
        }

    # Every session's raw regime (today's live-quote row included when the
    # session is still open), then the 2-day confirmation rule over the whole
    # chain -- it is path-dependent, so it has to start from the beginning,
    # exactly as the backtest does.
    full = pd.concat([df, pd.DataFrame([live_row])], ignore_index=True) if live_row else df
    raw_decisions = [
        decide(r.growth_up, r.breakeven_above_target, r.breakeven_momentum_up, r.asset_momentum_up)
        for r in full.itertuples()
    ]
    raw_holdings = [d["holding"] for d in raw_decisions]
    confirmed_holdings = confirmed(raw_holdings, CONFIRM_DAYS)

    def decision_at(i: int) -> dict:
        d = dict(raw_decisions[i])  # growthUp / inflationOn are today's RAW signals
        d["holding"] = confirmed_holdings[i]
        d["regime"] = TRADED_REGIME_MAP[d["holding"]]
        d["rawHolding"] = raw_holdings[i]
        d["rawRegime"] = TRADED_REGIME_MAP[raw_holdings[i]]
        d["pending"] = raw_holdings[i] != confirmed_holdings[i]
        d["date"] = str(today)[:10] if (live_row and i == len(full) - 1) else str(full["trading_date"].iloc[i])[:10]
        return d

    preview = decision_at(len(full) - 1)
    # Held today = decided at the previous session's close.
    current = decision_at(len(full) - 2)

    # Last HISTORY_DAYS sessions of every input signal, each tagged with the
    # (confirmed) holding in force that day -- feeds the email's signal charts.
    history = full.tail(HISTORY_DAYS).reset_index(drop=True)
    history["rawHolding"] = raw_holdings[-HISTORY_DAYS:]
    history["holding"] = confirmed_holdings[-HISTORY_DAYS:]

    preview["inputs"] = {
        "spx": spx,
        "sma200": float(sma),
        "breakeven": float(last["inflation_level"]),
        "breakevenTarget": BREAKEVEN_TARGET,
        "inflationAsOf": str(inflation_as_of)[:10],
    }
    return {"current": current, "preview": preview, "isLive": live_prices is not None, "livePrices": live_prices,
            "history": history}


def main() -> None:
    p = build_preview()
    print(f"Currently held (decided at the close of {p['current']['date']}): {p['current']['holding']} ({p['current']['regime']})")
    kind = "Live intraday preview" if p["isLive"] else "Today's final decision (already closed)"
    print(f"{kind} (as of {p['preview']['date']}): {p['preview']['holding']} ({p['preview']['regime']})")
    print(f"  inputs: {p['preview']['inputs']}")
    if p["isLive"]:
        print("  live quotes: " + ", ".join(f"{k}={v:.2f}" for k, v in p["livePrices"].items()))


if __name__ == "__main__":
    main()
