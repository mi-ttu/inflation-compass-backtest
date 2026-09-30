"""Parameterized simulator for the Inflation Compass Hybrid QLD/XLE daily-signal
variant (backtest/simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal.py),
for the robustness tests.

Same rules and inputs as transform/build_signals_extended.py:
  growth_up    = S&P 500 close > its SMA(sma)
  inflation_on = breakeven > threshold AND (breakeven rising over `mom` trading
                 days [3 calendar months before 2003, EXPINF5YR era]
                 OR the sector-basket ratio's `basket`-day slope > 0)
  regime -> holding: reflation XLE, goldilocks QLD, stagflation XLU,
                     slowdown 50/50 XLP+IEF (drifting within each holding run)
  1-day lag: the holding decided at day t's close earns day t+1.

Every setting is a parameter, holdings can be swapped, the inflation inputs can
be lagged (FRED publishes them a day late), and trading costs can be added.
validate() checks the published settings reproduce the real backtest exactly.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "transform"))
sys.path.insert(0, str(ROOT / "backtest"))
import build_signals_extended as BSE  # noqa: E402
from simulate_extended_levered_monthly import spliced_series_unlevered  # noqa: E402
from simulate_extended_monthly import load_real_total_return  # noqa: E402
from simulate_hybrid_qld_goldilocks_xle_reflation import build_qld_extended  # noqa: E402

DB = ROOT / "data" / "curated.duckdb"
RAW = ROOT / "data" / "raw"
SPLICE = BSE.SPLICE_DATE
REGIMES = ["reflation", "goldilocks", "stagflation", "slowdown"]
PUBLISHED_MAP = ["XLE", "QLD", "XLU", "XLP+IEF"]  # holding per regime code 0..3


@dataclass(frozen=True)
class Params:
    sma: int = 200
    threshold: float = 2.0
    mom: int = 60
    basket: int = 60


PUBLISHED = Params()


def confirm(raw: np.ndarray, k: int) -> np.ndarray:
    """Persistence filter: the output only changes to a new value once the raw
    series has shown that value on k consecutive days (k=1: unchanged)."""
    if k <= 1:
        return raw.copy()
    out = raw.copy()
    cur = raw[0]
    run = 1
    for i in range(1, len(raw)):
        run = run + 1 if raw[i] == raw[i - 1] else 1
        if raw[i] != cur and run >= k:
            cur = raw[i]
        out[i] = cur
    return out


def fast_slope(y: np.ndarray, w: int) -> np.ndarray:
    """Same least-squares slope as BSE.rolling_slope, via one convolution."""
    x = np.arange(w) - (w - 1) / 2
    out = np.full(len(y), np.nan)
    if len(y) >= w:
        out[w - 1:] = np.convolve(y, x[::-1], "valid") / (x ** 2).sum()
    return out


class Inputs:
    """Raw daily inputs on the strategy's own calendar, plus holding legs."""

    def __init__(self):
        con = duckdb.connect(str(DB), read_only=True)
        g = BSE.load_growth(con).set_index("trading_date")
        basket = BSE.load_sector_basket_spliced(con).set_index("trading_date")
        infl = BSE.load_inflation_spliced(con).set_index("trading_date")
        t5 = con.execute("SELECT observation_date d, value v FROM fred_series WHERE series_id='T5YIE' ORDER BY 1").df()
        ex = con.execute("SELECT observation_date d, value v FROM fred_series WHERE series_id='EXPINF5YR' ORDER BY 1").df()
        legs = {"QLD": build_qld_extended(con), "XLE": spliced_series_unlevered(con, "XLE"),
                "XLU": spliced_series_unlevered(con, "XLU"), "XLP": spliced_series_unlevered(con, "XLP"),
                "IEF": spliced_series_unlevered(con, "IEF"), "SPX": load_real_total_return(con, "^GSPC"),
                "NDX": load_real_total_return(con, "^NDX"), "XLK": load_real_total_return(con, "XLK")}
        con.close()
        idx = g.index.intersection(basket.index).intersection(infl.index)
        self.index = idx
        self.spx = g.loc[idx, "spy_close"].to_numpy(float)
        self.ratio = basket.loc[idx, "sector_basket_ratio"].to_numpy(float)
        self.level = infl.loc[idx, "inflation_level"].to_numpy(float)
        self.source_t5 = (infl.loc[idx, "inflation_signal_source"] == "T5YIE").to_numpy()
        t5["d"], ex["d"] = pd.to_datetime(t5["d"]), pd.to_datetime(ex["d"])
        self.t5 = t5.set_index("d")["v"]
        self.ex = ex.set_index("d")["v"]
        self.legs = pd.DataFrame({k: v.reindex(idx) for k, v in legs.items()})
        rf = pd.read_csv(RAW / "fred" / "DTB3.csv", parse_dates=["observation_date"], na_values=".") \
            if (RAW / "fred" / "DTB3.csv").exists() else None
        self.rf = (rf.set_index("observation_date")["DTB3"].reindex(idx, method="ffill").fillna(0) / 100 / 252) if rf is not None else pd.Series(0.0, index=idx)

    # ------------------------------------------------------------ signals
    def breakeven_momentum(self, mom: int) -> np.ndarray:
        """Rising-breakeven flag. T5YIE era: level > level `mom` T5YIE rows ago
        (as build_signals_extended does). EXPINF5YR era: vs the value
        round(mom/20) calendar months earlier (published: 60 days <-> 3 months)."""
        out = np.zeros(len(self.index), dtype=bool)
        t5 = self.t5[self.t5.index >= SPLICE]
        t5_up = (t5 > t5.shift(mom)).reindex(self.index)
        months = max(1, round(mom / 20))
        ex = self.ex[self.ex.index < SPLICE]
        look = pd.merge_asof(pd.DataFrame({"d": ex.index - pd.DateOffset(months=months)}).sort_values("d"),
                             self.ex.rename("lv").reset_index().rename(columns={"index": "d"}).sort_values("d"),
                             on="d", direction="backward")["lv"].to_numpy()
        ex_up = pd.Series(ex.to_numpy() > look, index=ex.index).reindex(self.index)
        m = self.source_t5
        out[m] = t5_up.to_numpy()[m].astype(bool)
        out[~m] = ex_up.to_numpy()[~m].astype(bool)
        return out

    def regimes(self, p: Params = PUBLISHED, infl_lag: int = 0, spx=None, ratio=None, level=None,
                infl_confirm: int = 1, regime_confirm: int = 1, parts: bool = False):
        """Regime code per day (-1 during warmup). infl_confirm=k: the inflation
        signal must hold for k consecutive days before a change is acted on;
        regime_confirm=k: the same for the whole regime. parts=True also
        returns (growth, raw inflation_on) for callers that need them."""
        spx = self.spx if spx is None else spx
        ratio = self.ratio if ratio is None else ratio
        level = self.level if level is None else level
        sma = pd.Series(spx).rolling(p.sma, min_periods=p.sma).mean().to_numpy()
        growth = spx > sma
        above = level > p.threshold
        mom_up = self.breakeven_momentum(p.mom) if level is self.level else np.concatenate([np.zeros(p.mom, bool), level[p.mom:] > level[:-p.mom]])
        if infl_lag:
            above = np.concatenate([np.zeros(infl_lag, bool), above[:-infl_lag]])
            mom_up = np.concatenate([np.zeros(infl_lag, bool), mom_up[:-infl_lag]])
        basket_up = fast_slope(ratio, p.basket) > 0
        infl_raw = above & (mom_up | basket_up)
        infl_on = confirm(infl_raw, infl_confirm)
        code = np.where(growth, np.where(infl_on, 0, 1), np.where(infl_on, 2, 3)).astype(np.int8)
        code[np.isnan(sma)] = -1
        if regime_confirm > 1:
            valid = code >= 0
            code[valid] = confirm(code[valid], regime_confirm)
        return (code, growth, infl_raw, infl_on) if parts else code

    # ------------------------------------------------------------ returns
    def leg_matrix(self, mapping=PUBLISHED_MAP, qld_cost: bool = False) -> np.ndarray:
        """(n, 4) daily returns of the holding for each regime code; the
        XLP+IEF column is handled in returns() (drifting 50/50 per run)."""
        L = self.legs.copy()
        if qld_cost:  # pre-2006 QLD stand-in with financing (1x T-bill) and a 0.95% fee
            real_start = pd.Timestamp("2006-06-22")
            L.loc[L.index < real_start, "QLD"] = 2 * L["NDX"] - self.rf - 0.0095 / 252
        cols = []
        for h in mapping:
            cols.append(np.full(len(L), np.nan) if h == "XLP+IEF" else L[{"QQQ": "NDX", "SPY": "SPX"}.get(h, h)].to_numpy(float))
        return np.column_stack(cols)

    def returns(self, code: np.ndarray, mapping=PUBLISHED_MAP, delay: int = 1, cost_bps: float = 0.0,
                qld_cost: bool = False, legs: np.ndarray | None = None, xlp_ief: np.ndarray | None = None) -> pd.Series:
        n = len(code)
        M = self.leg_matrix(mapping, qld_cost) if legs is None else legs
        xlp, ief = (self.legs["XLP"].to_numpy(float), self.legs["IEF"].to_numpy(float)) if xlp_ief is None else xlp_ief
        exp = np.full(n, -1, dtype=np.int8)
        exp[delay:] = code[: n - delay]
        r = np.full(n, np.nan)
        slow = [k for k, h in enumerate(mapping) if h == "XLP+IEF"]
        i = 0
        while i < n:
            j = i
            while j + 1 < n and exp[j + 1] == exp[i]:
                j += 1
            c = exp[i]
            if c >= 0:
                if c in slow:
                    a = np.cumprod(1 + xlp[i:j + 1]); b = np.cumprod(1 + ief[i:j + 1])
                    nav = 0.5 * a + 0.5 * b
                    r[i:j + 1] = nav / np.concatenate([[1.0], nav[:-1]]) - 1
                else:
                    r[i:j + 1] = M[i:j + 1, c]
                if cost_bps and i > 0 and exp[i - 1] >= 0:
                    r[i] -= 2 * cost_bps / 1e4
            i = j + 1
        return pd.Series(r, index=self.index)


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"cagr": np.nan, "sharpe": np.nan, "mdd": np.nan, "vol": np.nan}
    g = (1 + r).cumprod(); yrs = len(r) / 252; vol = r.std() * np.sqrt(252)
    return {"cagr": g.iloc[-1] ** (1 / yrs) - 1, "sharpe": r.mean() * 252 / vol if vol else np.nan,
            "mdd": (g / g.cummax() - 1).min(), "vol": vol}


def validate(inp: Inputs | None = None) -> dict:
    inp = inp or Inputs()
    code = inp.regimes()
    con = duckdb.connect(str(DB), read_only=True)
    sig = con.execute("SELECT trading_date, growth_up, inflation_on FROM signals_daily_extended").df()
    con.close()
    sig["trading_date"] = pd.to_datetime(sig["trading_date"])
    sig = sig.set_index("trading_date").reindex(inp.index)
    ref = np.where(sig["growth_up"], np.where(sig["inflation_on"], 0, 1), np.where(sig["inflation_on"], 2, 3))
    m = (code >= 0) & sig["growth_up"].notna().to_numpy()
    r = inp.returns(code)
    bt = pd.read_csv(ROOT / "backtest" / "hybrid_qld_goldilocks_xle_reflation_daily_signal_returns.csv",
                     parse_dates=["trading_date"]).set_index("trading_date")["model_return"]
    j = pd.concat([r.rename("mine"), bt.rename("bt")], axis=1, join="inner").dropna()
    return {"regime_agreement": float((code[m] == ref[m]).mean()), "days": int(m.sum()),
            "max_abs_return_diff": float((j["mine"] - j["bt"]).abs().max()), "days_returns": len(j),
            "cagr_mine": stats(j["mine"])["cagr"], "cagr_backtest": stats(j["bt"])["cagr"]}


if __name__ == "__main__":
    print(validate())
