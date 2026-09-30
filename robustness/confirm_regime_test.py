"""Same checks as confirm_test.py, for the whole-regime version of the rule:
the regime (not just the inflation signal) must read the same on k
consecutive closes before the holding changes. Writes
robustness/results_confirm_regime.json.

Usage: .venv/Scripts/python.exe robustness/confirm_regime_test.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import engine as E
import run_tests as T
from confirm_test import S, trade_stats

HERE = Path(__file__).resolve().parent
FULL, IN, OOS_END = T.FULL, T.IN_START, T.OOS_END


def main():
    inp = E.Inputs()
    out = {"k_sweep": [], "random": {}, "intraday": {}, "bootstrap": {}, "cost_curve": []}
    for k in range(1, 6):
        code = inp.regimes(E.PUBLISHED, regime_confirm=k)
        pt = {"k": k, **trade_stats(inp, code)}
        for c in (0, 10, 25):
            r = inp.returns(code, cost_bps=c)
            pt[c] = {"full": S(r), "oos": S(r, FULL, OOS_END), "in": S(r, IN)}
        out["k_sweep"].append(pt)
        print(f"regime k={k}: trades/yr {pt['trades_per_year']:4.1f} short {pt['short_holds']:4.0%} | 0bps full {pt[0]['full']['cagr']:5.1%} "
              f"oos {pt[0]['oos']['cagr']:5.1%} in {pt[0]['in']['cagr']:5.1%} MDD {pt[0]['full']['mdd']:5.1%} Sharpe {pt[0]['full']['sharpe']:.2f} | "
              f"10bps {pt[10]['full']['cagr']:5.1%} | 25bps {pt[25]['full']['cagr']:5.1%}")

    T.RNG = np.random.default_rng(11)
    diffs = {c: {"full": [], "oos": [], "in": [], "mdd": [], "sharpe": []} for c in (0, 10)}
    for _ in range(T.N_RANDOM):
        p = T.random_params()
        a, b = inp.regimes(p), inp.regimes(p, regime_confirm=2)
        for c in (0, 10):
            ra, rb = inp.returns(a, cost_bps=c), inp.returns(b, cost_bps=c)
            for key, (lo, hi) in {"full": (FULL, None), "oos": (FULL, OOS_END), "in": (IN, None)}.items():
                diffs[c][key].append(E.stats(T.w(rb, lo, hi))["cagr"] - E.stats(T.w(ra, lo, hi))["cagr"])
            sa, sb = E.stats(T.w(ra, FULL)), E.stats(T.w(rb, FULL))
            diffs[c]["mdd"].append(sb["mdd"] - sa["mdd"]); diffs[c]["sharpe"].append(sb["sharpe"] - sa["sharpe"])
    for c in (0, 10):
        out["random"][c] = {k: {"share_improved": float((np.array(v) > 0).mean()), "median_gain": float(np.median(v))} for k, v in diffs[c].items()}
        r = out["random"][c]
        print(f"random sets {c}bps: CAGR better full {r['full']['share_improved']:.0%} ({r['full']['median_gain']*100:+.1f}), oos {r['oos']['share_improved']:.0%} "
              f"({r['oos']['median_gain']*100:+.1f}), in {r['in']['share_improved']:.0%} ({r['in']['median_gain']*100:+.1f}); "
              f"shallower max DD {r['mdd']['share_improved']:.0%} ({r['mdd']['median_gain']*100:+.1f}); Sharpe better {r['sharpe']['share_improved']:.0%}")

    # live-like 2:30 PM
    con = duckdb.connect(str(E.DB), read_only=True)
    closes = con.execute("SELECT ticker, trading_date, close FROM equity_prices WHERE ticker IN ('XLE','XLI','XLF','XLB','XLU','XLV','XLP')").df()
    con.close()
    closes["trading_date"] = pd.to_datetime(closes["trading_date"])
    closes = closes.pivot(index="trading_date", columns="ticker", values="close").reindex(inp.index)
    spx_i = T.intraday("^GSPC"); sec_i = {t: T.intraday(t) for t in ["XLE", "XLI", "XLF", "XLB", "XLU", "XLV", "XLP"]}
    p = E.PUBLISHED
    above = np.concatenate([[False], (inp.level > p.threshold)[:-1]])
    momup = np.concatenate([[False], inp.breakeven_momentum(p.mom)[:-1]])
    raw_close = inp.regimes(p, infl_lag=1)            # what the close would say, inflation a day late
    conf_close = inp.regimes(p, infl_lag=1, regime_confirm=2)
    pos = {d: i for i, d in enumerate(inp.index)}
    days = [d for d in inp.index if d in spx_i.index and all(d in s.index for s in sec_i.values())]
    for k in (1, 2):
        live = (raw_close if k == 1 else conf_close).copy()
        for d in days:
            i = pos[d]
            s = np.append(inp.spx[i - p.sma + 1:i], spx_i.loc[d]); g = s[-1] > s.mean()
            rets = {t: sec_i[t].loc[d] / closes[t].iloc[i - 1] - 1 for t in sec_i}
            pr_ = sum(rets[t] * wt for t, wt in E.BSE.POSITIVE_BASKET.items()); nr = sum(rets[t] * wt for t, wt in E.BSE.NEGATIVE_BASKET.items())
            ratio = np.append(inp.ratio[i - p.basket + 1:i], inp.ratio[i - 1] * (1 + pr_) / (1 + nr))
            on = bool(above[i] and (momup[i] or E.fast_slope(ratio, p.basket)[-1] > 0))
            today = (0 if on else 1) if g else (2 if on else 3)
            if k == 1:
                live[i] = today
            else:  # switch only if today's live regime matches yesterday's close regime
                live[i] = today if (today != live[i - 1] and today == raw_close[i - 1]) else live[i - 1]
        m = np.zeros(len(live), bool); m[[pos[d] for d in days]] = True
        first = inp.index[m][0]
        ref = inp.regimes(p) if k == 1 else inp.regimes(p, regime_confirm=2)
        out["intraday"][k] = {"from": str(first.date()), "days": int(m.sum()),
                              "close": S(inp.returns(ref), first), "live": S(inp.returns(live), first),
                              "close_10bps": S(inp.returns(ref, cost_bps=10), first), "live_10bps": S(inp.returns(live, cost_bps=10), first),
                              "trades_live": float(((live[m][1:] != live[m][:-1]).sum()) / (m.sum() / 252))}
        it = out["intraday"][k]
        print(f"live-like regime k={k} ({it['from']}..): close {it['close']['cagr']:.1%} live {it['live']['cagr']:.1%} | 10bps close {it['close_10bps']['cagr']:.1%} live {it['live_10bps']['cagr']:.1%} | live trades/yr {it['trades_live']:.1f}")

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
            code = inp.regimes(p, spx=spx, ratio=ratio, level=level[ix].copy(), regime_confirm=k)
            r = E.Inputs.returns(sub, code, legs=L[ix], xlp_ief=(xlp[ix], ief[ix]), cost_bps=10).to_numpy()[warm:]
            res[k].append(E.stats(pd.Series(r)))
    for key in ("cagr", "mdd", "sharpe"):
        d = np.array([b[key] - a[key] for a, b in zip(res[1], res[2])])
        out["bootstrap"][key] = {"share_improved": float((d > 0).mean()), "median_change": float(np.median(d))}
    out["bootstrap"]["median"] = {k: {m: float(np.median([x[m] for x in res[k]])) for m in ("cagr", "mdd", "sharpe")} for k in (1, 2)}
    b = out["bootstrap"]
    print(f"bootstrap @10bps: CAGR better {b['cagr']['share_improved']:.0%} ({b['cagr']['median_change']*100:+.1f}), "
          f"max DD shallower {b['mdd']['share_improved']:.0%} ({b['mdd']['median_change']*100:+.1f}), Sharpe better {b['sharpe']['share_improved']:.0%}")
    (HERE / "results_confirm_regime.json").write_text(json.dumps(out, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


if __name__ == "__main__":
    main()
