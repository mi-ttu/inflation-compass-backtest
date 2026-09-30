"""Test a two-day confirmation rule for the Hybrid QLD/XLE daily variant.

Rule under test ("inflation 2-day"): the inflation signal must read the same
on two consecutive closes before a change in it is acted on; the growth
signal still acts immediately. Compared with: the published rule, confirming
the whole regime for 2 days, and 1-5 days of inflation confirmation.

Checked on 1990-2002 (before the published backtest) and 2003-2026
separately, at 0/10/25 bps per trade, across the 300 random nearby
parameter sets from run_tests.py (same seed), against the live-like 2:30 PM
decision, and on 300 block-bootstrap histories. Writes
robustness/results_confirm.json.

Usage: .venv/Scripts/python.exe robustness/confirm_test.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import engine as E
import run_tests as T

HERE = Path(__file__).resolve().parent
FULL, IN, OOS_END = T.FULL, T.IN_START, T.OOS_END
VARIANTS = [("Published (no confirmation)", {}),
            ("Inflation signal must hold 2 days", {"infl_confirm": 2}),
            ("Whole regime must hold 2 days", {"regime_confirm": 2})]
COSTS = [0, 10, 25]


def S(r, a=FULL, b=None):
    return T.S(r, a, b)


def trade_stats(inp, code):
    exp = np.concatenate([[-1], code[:-1]])
    ok = (code >= 0) & (exp >= 0)
    sw = ((code != exp) & ok).sum() / (ok.sum() / 252)
    runs = pd.Series(code[code >= 0]); lens = runs.groupby((runs != runs.shift()).cumsum()).size()
    return {"trades_per_year": float(sw), "short_holds": float((lens <= 3).mean()), "median_hold_days": float(lens.median())}


def main():
    inp = E.Inputs()
    out = {"variants": [], "k_sweep": [], "random": {}, "intraday": {}, "bootstrap": {}}

    for label, kw in VARIANTS:
        code = inp.regimes(E.PUBLISHED, **kw)
        row = {"label": label, **trade_stats(inp, code), "by_cost": {}}
        for c in COSTS:
            r = inp.returns(code, cost_bps=c)
            row["by_cost"][c] = {"full": S(r), "oos": S(r, FULL, OOS_END), "in": S(r, IN)}
        out["variants"].append(row)
        b0, b10 = row["by_cost"][0], row["by_cost"][10]
        print(f"{label:36} trades/yr {row['trades_per_year']:5.1f} short {row['short_holds']:4.0%} | "
              f"0bps full {b0['full']['cagr']:5.1%} oos {b0['oos']['cagr']:5.1%} in {b0['in']['cagr']:5.1%} MDD {b0['full']['mdd']:5.1%} | "
              f"10bps full {b10['full']['cagr']:5.1%} oos {b10['oos']['cagr']:5.1%} in {b10['in']['cagr']:5.1%}")

    for k in range(1, 6):
        code = inp.regimes(E.PUBLISHED, infl_confirm=k)
        pt = {"k": k, **trade_stats(inp, code)}
        for c in (0, 10):
            r = inp.returns(code, cost_bps=c)
            pt[c] = {"full": S(r), "oos": S(r, FULL, OOS_END), "in": S(r, IN)}
        out["k_sweep"].append(pt)
        print(f"k={k}: trades/yr {pt['trades_per_year']:5.1f}  0bps {pt[0]['full']['cagr']:5.1%} (oos {pt[0]['oos']['cagr']:5.1%}, in {pt[0]['in']['cagr']:5.1%})  10bps {pt[10]['full']['cagr']:5.1%}")

    # Same 300 random parameter sets as run_tests (same seed and draw order)
    T.RNG = np.random.default_rng(11)
    diffs = {c: {"full": [], "oos": [], "in": []} for c in (0, 10)}
    for _ in range(T.N_RANDOM):
        p = T.random_params()
        a, b = inp.regimes(p), inp.regimes(p, infl_confirm=2)
        for c in (0, 10):
            ra, rb = inp.returns(a, cost_bps=c), inp.returns(b, cost_bps=c)
            for key, (lo, hi) in {"full": (FULL, None), "oos": (FULL, OOS_END), "in": (IN, None)}.items():
                diffs[c][key].append(E.stats(T.w(rb, lo, hi))["cagr"] - E.stats(T.w(ra, lo, hi))["cagr"])
    for c in (0, 10):
        out["random"][c] = {k: {"share_improved": float((np.array(v) > 0).mean()), "median_gain": float(np.median(v)),
                                "p5": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95))} for k, v in diffs[c].items()}
        print(f"random sets, {c}bps: improved in " + ", ".join(f"{k} {d['share_improved']:.0%} (median {d['median_gain']*100:+.1f} pts)" for k, d in out["random"][c].items()))

    # Live-like 2:30 PM decision with the rule (inflation data one day late, as the live preview does)
    con = duckdb.connect(str(E.DB), read_only=True)
    closes = con.execute("SELECT ticker, trading_date, close FROM equity_prices WHERE ticker IN ('XLE','XLI','XLF','XLB','XLU','XLV','XLP')").df()
    con.close()
    closes["trading_date"] = pd.to_datetime(closes["trading_date"])
    closes = closes.pivot(index="trading_date", columns="ticker", values="close").reindex(inp.index)
    spx_i = T.intraday("^GSPC"); sec_i = {t: T.intraday(t) for t in ["XLE", "XLI", "XLF", "XLB", "XLU", "XLV", "XLP"]}
    p = E.PUBLISHED
    above = np.concatenate([[False], (inp.level > p.threshold)[:-1]])
    momup = np.concatenate([[False], inp.breakeven_momentum(p.mom)[:-1]])
    pos = {d: i for i, d in enumerate(inp.index)}
    days = [d for d in inp.index if d in spx_i.index and all(d in s.index for s in sec_i.values())]
    for k in (1, 2):
        code, growth, infl_raw, infl_conf = inp.regimes(p, infl_confirm=k, parts=True)
        live = code.copy()
        for d in days:
            i = pos[d]
            s = np.append(inp.spx[i - p.sma + 1:i], spx_i.loc[d]); g = s[-1] > s.mean()
            rets = {t: sec_i[t].loc[d] / closes[t].iloc[i - 1] - 1 for t in sec_i}
            pr_ = sum(rets[t] * wt for t, wt in E.BSE.POSITIVE_BASKET.items()); nr = sum(rets[t] * wt for t, wt in E.BSE.NEGATIVE_BASKET.items())
            ratio = np.append(inp.ratio[i - p.basket + 1:i], inp.ratio[i - 1] * (1 + pr_) / (1 + nr))
            raw_today = bool(above[i] and (momup[i] or E.fast_slope(ratio, p.basket)[-1] > 0))
            prev_conf = bool(infl_conf[i - 1])
            if k == 1 or raw_today == prev_conf:
                on = raw_today if k == 1 else prev_conf
            else:
                on = raw_today if raw_today == bool(infl_raw[i - 1]) else prev_conf  # held 2 days (yesterday's close + today)
            live[i] = (0 if on else 1) if g else (2 if on else 3)
        m = np.zeros(len(code), bool); m[[pos[d] for d in days]] = True
        first = inp.index[m][0]
        r_close, r_live = inp.returns(code), inp.returns(live)
        out["intraday"][k] = {"from": str(first.date()), "days": int(m.sum()), "agreement": float((live[m] == code[m]).mean()),
                              "close": S(r_close, first), "live": S(r_live, first),
                              "close_10bps": S(inp.returns(code, cost_bps=10), first), "live_10bps": S(inp.returns(live, cost_bps=10), first)}
        it = out["intraday"][k]
        print(f"live-like k={k}: agrees {it['agreement']:.1%}; CAGR close {it['close']['cagr']:.1%} live {it['live']['cagr']:.1%} | at 10bps close {it['close_10bps']['cagr']:.1%} live {it['live_10bps']['cagr']:.1%}")

    # Bootstrap: same histories for both rules
    rng = np.random.default_rng(5)
    msk = inp.index >= "2002-06-01"
    spx_r = pd.Series(inp.spx).pct_change().to_numpy()[msk]; ratio_r = pd.Series(inp.ratio).pct_change().to_numpy()[msk]
    level = inp.level[msk]; L = inp.leg_matrix()[msk]; xlp = inp.legs["XLP"].to_numpy(float)[msk]; ief = inp.legs["IEF"].to_numpy(float)[msk]
    n = msk.sum() - 1; warm = 300; res = {1: [], 2: []}
    sub = E.Inputs.__new__(E.Inputs); sub.index = pd.RangeIndex(n + warm)
    for _ in range(T.N_BOOT):
        st = rng.integers(1, n - T.BLOCK, size=(n + warm) // T.BLOCK + 1)
        ix = np.concatenate([np.arange(s, s + T.BLOCK) for s in st])[: n + warm]
        spx = 100 * np.cumprod(1 + spx_r[ix]); ratio = np.cumprod(1 + ratio_r[ix])
        for k in (1, 2):
            code = inp.regimes(p, spx=spx, ratio=ratio, level=level[ix].copy(), infl_confirm=k)
            r = E.Inputs.returns(sub, code, legs=L[ix], xlp_ief=(xlp[ix], ief[ix]), cost_bps=10).to_numpy()[warm:]
            res[k].append(E.stats(pd.Series(r)))
    d_c = np.array([b["cagr"] - a["cagr"] for a, b in zip(res[1], res[2])])
    d_m = np.array([b["mdd"] - a["mdd"] for a, b in zip(res[1], res[2])])
    out["bootstrap"] = {"share_cagr_improved": float((d_c > 0).mean()), "median_cagr_gain": float(np.median(d_c)),
                        "share_mdd_improved": float((d_m > 0).mean()), "median_mdd_change": float(np.median(d_m)),
                        "median_cagr": {k: float(np.median([x["cagr"] for x in res[k]])) for k in (1, 2)},
                        "median_mdd": {k: float(np.median([x["mdd"] for x in res[k]])) for k in (1, 2)}}
    b = out["bootstrap"]
    print(f"bootstrap @10bps: 2-day rule higher CAGR in {b['share_cagr_improved']:.0%} of histories (median {b['median_cagr_gain']*100:+.1f} pts); "
          f"shallower max DD in {b['share_mdd_improved']:.0%} (median {b['median_mdd_change']*100:+.1f} pts)")
    (HERE / "results_confirm.json").write_text(json.dumps(out, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


if __name__ == "__main__":
    main()
