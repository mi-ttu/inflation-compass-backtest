"""Inflation Compass (Hybrid QLD/XLE, daily) robustness tests 1-5.
Writes robustness/results.json.

  1. Out of sample and holdings: 1990-2002 (before Varadi's published 2003+
     backtest) vs 2003-2026; the same signals with other goldilocks holdings;
     all 24 ways of assigning the four holdings to the four regimes
  2. Parameter robustness: one-at-a-time sweeps + 300 random joint nudges
  3. Execution stress: costs, a day of delay, inflation data 1-2 days late,
     a costed QLD stand-in before 2006, and the live 2:30 PM CT decision
     (60-minute bars, inflation one day late) over the last ~2 years
  4. Walk-forward: each January pick the best settings by trailing Sharpe
  5. Block-bootstrap synthetic histories (2003 on, daily T5YIE era)

Usage: .venv/Scripts/python.exe robustness/run_tests.py
"""
from __future__ import annotations

import itertools
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import engine as E

HERE = Path(__file__).resolve().parent
FULL, IN_START, OOS_END, PUB_DATE = "1990-01-01", "2003-01-02", "2002-12-31", "2026-07-27"
RNG = np.random.default_rng(11)
N_RANDOM, N_BOOT, BLOCK = 300, 300, 126


def w(r, a=None, b=None):
    if a: r = r[r.index >= a]
    if b: r = r[r.index <= b]
    return r


def S(r, a=FULL, b=None):
    return {k: (None if pd.isna(v) else float(v)) for k, v in E.stats(w(r, a, b)).items()}


def triple(r):
    return {"full": S(r), "oos": S(r, FULL, OOS_END), "in": S(r, IN_START)}


def pr(tag, label, t):
    print(f"[{tag}] {label:40} full {t['full']['cagr']:6.1%}/{t['full']['mdd']:6.1%}  1990-2002 {t['oos']['cagr']:6.1%}/{t['oos']['mdd']:6.1%}  2003+ {t['in']['cagr']:6.1%}/{t['in']['mdd']:6.1%}")


# ------------------------------------------------------------------ test 1
def test1(inp):
    code = inp.regimes()
    pub = inp.returns(code)
    spx = inp.legs["SPX"]; qld = inp.legs["QLD"]
    out = {"split": {"published": triple(pub), "spy": triple(spx), "qld": triple(qld),
                     "published_qld_costed": triple(inp.returns(code, qld_cost=True)),
                     "since_publication": {"strategy": S(pub, PUB_DATE), "spy": S(spx, PUB_DATE),
                                           "days": int((pub.index >= PUB_DATE).sum())}}}
    for k in ("published", "published_qld_costed", "spy", "qld"):
        pr(1, k, out["split"][k])
    swaps = []
    for label, h in (("QLD (2× Nasdaq-100, published)", "QLD"), ("QQQ (Nasdaq-100)", "QQQ"), ("SPY (S&P 500)", "SPY"), ("XLK (tech sector, Varadi's original)", "XLK")):
        m = ["XLE", h, "XLU", "XLP+IEF"]
        r = inp.returns(code, mapping=m)
        swaps.append({"label": label, "holding": h, "in": S(r, IN_START), "full": S(r) if h != "XLK" else None,
                      "bh_in": S(inp.legs[{"QQQ": "NDX", "SPY": "SPX"}.get(h, h)], IN_START)})
        print(f"[1] swap {label:38} 2003+ {swaps[-1]['in']['cagr']:6.1%} Sharpe {swaps[-1]['in']['sharpe']:.2f} vs its B&H {swaps[-1]['bh_in']['cagr']:6.1%}/{swaps[-1]['bh_in']['sharpe']:.2f}")
    out["swaps"] = swaps
    perms = []
    for m in itertools.permutations(E.PUBLISHED_MAP):
        r = inp.returns(code, mapping=list(m))
        perms.append({"map": list(m), "full": S(r), "in": S(r, IN_START), "oos": S(r, FULL, OOS_END), "published": list(m) == E.PUBLISHED_MAP})
    for key in ("full", "oos", "in"):
        order = sorted(perms, key=lambda x: -x[key]["sharpe"])
        rank = next(i for i, x in enumerate(order) if x["published"]) + 1
        print(f"[1] permutations {key}: published mapping ranks {rank} of 24 by Sharpe")
    out["permutations"] = perms
    return out


# ------------------------------------------------------------------ test 2
GRIDS = {"sma": [100, 150, 200, 250, 300], "threshold": [1.5, 1.75, 2.0, 2.25, 2.5],
         "mom": [20, 40, 60, 90, 120], "basket": [20, 40, 60, 90, 120]}


def random_params():
    return E.Params(sma=int(RNG.integers(150, 251)), threshold=float(RNG.uniform(1.75, 2.25)),
                    mom=int(RNG.integers(40, 81)), basket=int(RNG.integers(40, 81)))


def test2(inp):
    sweeps = {}
    for name, vals in GRIDS.items():
        pts = []
        for v in vals:
            r = inp.returns(inp.regimes(replace(E.PUBLISHED, **{name: v})))
            pts.append({"value": v, "full": S(r), "in": S(r, IN_START), "oos": S(r, FULL, OOS_END)})
        sweeps[name] = pts
        print(f"[2] {name:10} " + "  ".join(f"{p['value']}: {p['full']['cagr']:.1%}" for p in pts))
    cands, series = [], {}
    for i in range(N_RANDOM):
        p = random_params()
        r = inp.returns(inp.regimes(p))
        series[i] = r
        cands.append({"params": asdict(p), "full": S(r), "in": S(r, IN_START), "oos": S(r, FULL, OOS_END)})
    pub = inp.returns(inp.regimes())
    pubs = {"full": S(pub), "in": S(pub, IN_START), "oos": S(pub, FULL, OOS_END)}
    for key in ("full", "in", "oos"):
        cg = np.array([c[key]["cagr"] for c in cands]); sh = np.array([c[key]["sharpe"] for c in cands])
        print(f"[2] random {key}: CAGR median {np.median(cg):.1%} (5-95% {np.percentile(cg,5):.1%}-{np.percentile(cg,95):.1%}); "
              f"published {pubs[key]['cagr']:.1%} pct {100*(cg < pubs[key]['cagr']).mean():.0f}; Sharpe pct {100*(sh < pubs[key]['sharpe']).mean():.0f}")
    return {"sweeps": sweeps, "random": cands, "published": pubs}, series, pub


# ------------------------------------------------------------------ test 3
def intraday(ticker, hour_et=15.5):
    f = sorted((E.RAW / "yfinance_intraday").glob(f"{ticker.replace('^','')}_60m_*.csv"))[-1]
    d = pd.read_csv(f)
    d.index = pd.to_datetime(d.iloc[:, 0], utc=True).dt.tz_convert("America/New_York")
    end = d.index + pd.Timedelta(hours=1)
    sel = d[(end.hour == 15) & (end.minute == 30)]
    sel.index = pd.to_datetime(sel.index.date)
    return sel["Close"]


def test3(inp):
    code = inp.regimes()
    rows = []
    scen = [("As backtested (close signal, next-day return, no costs)", {}, {}),
            ("Inflation data 1 day late", {"infl_lag": 1}, {}),
            ("Inflation data 2 days late", {"infl_lag": 2}, {}),
            ("One extra day of delay", {}, {"delay": 2}),
            ("5 bps per trade", {}, {"cost_bps": 5}), ("10 bps per trade", {}, {"cost_bps": 10}), ("25 bps per trade", {}, {"cost_bps": 25}),
            ("QLD stand-in before 2006 pays financing + fee", {}, {"qld_cost": True}),
            ("Realistic: inflation 1 day late + 10 bps + costed QLD", {"infl_lag": 1}, {"cost_bps": 10, "qld_cost": True})]
    for label, sk, rk in scen:
        r = inp.returns(inp.regimes(E.PUBLISHED, **sk), **rk)
        rows.append({"scenario": label, **triple(r)})
        pr(3, label[:40], rows[-1])
    exp = np.concatenate([[-1], code[:-1]])
    switches = ((code != exp) & (exp >= 0) & (code >= 0)).sum() / (len(code) / 252)

    # Live-like decision: 3:30 PM ET S&P 500 and sector prices, inflation one day late.
    con = duckdb.connect(str(E.DB), read_only=True)
    closes = con.execute("SELECT ticker, trading_date, close FROM equity_prices WHERE ticker IN ('XLE','XLI','XLF','XLB','XLU','XLV','XLP')").df()
    con.close()
    closes["trading_date"] = pd.to_datetime(closes["trading_date"])
    closes = closes.pivot(index="trading_date", columns="ticker", values="close").reindex(inp.index)
    spx_i = intraday("^GSPC")
    sec_i = {t: intraday(t) for t in ["XLE", "XLI", "XLF", "XLB", "XLU", "XLV", "XLP"]}
    lagged = inp.regimes(E.PUBLISHED, infl_lag=1)  # gives the lagged inflation part per day
    p = E.PUBLISHED
    above = np.concatenate([[False], (inp.level > p.threshold)[:-1]])
    momup = np.concatenate([[False], inp.breakeven_momentum(p.mom)[:-1]])
    live = code.copy()
    pos = {d: i for i, d in enumerate(inp.index)}
    days = [d for d in inp.index if d in spx_i.index and all(d in s.index for s in sec_i.values())]
    for d in days:
        i = pos[d]
        s = np.append(inp.spx[i - p.sma + 1:i], spx_i.loc[d])
        growth = s[-1] > s.mean()
        rets = {t: sec_i[t].loc[d] / closes[t].iloc[i - 1] - 1 for t in sec_i}
        posr = sum(rets[t] * wt for t, wt in E.BSE.POSITIVE_BASKET.items())
        negr = sum(rets[t] * wt for t, wt in E.BSE.NEGATIVE_BASKET.items())
        ratio = np.append(inp.ratio[i - p.basket + 1:i], inp.ratio[i - 1] * (1 + posr) / (1 + negr))
        basket_up = E.fast_slope(ratio, p.basket)[-1] > 0
        infl_on = above[i] and (momup[i] or basket_up)
        live[i] = (0 if infl_on else 1) if growth else (2 if infl_on else 3)
    m = np.zeros(len(code), bool); m[[pos[d] for d in days]] = True
    first = inp.index[m][0]
    r_close = inp.returns(code); r_live = inp.returns(live); r_lag = inp.returns(lagged)
    dis = [{"date": str(d.date()), "close": E.REGIMES[code[pos[d]]], "live": E.REGIMES[live[pos[d]]]} for d in inp.index[m] if live[pos[d]] != code[pos[d]]]
    out = {"frictions": rows, "switches_per_year": float(switches),
           "intraday": {"days": int(m.sum()), "from": str(first.date()), "to": str(inp.index[m][-1].date()),
                        "agreement": float((live[m] == code[m]).mean()), "close_signal": S(r_close, first),
                        "live_signal": S(r_live, first), "disagreements": dis}}
    it = out["intraday"]
    print(f"[3] live-like 3:30 PM ET, {it['from']}..{it['to']} ({it['days']} days): regime agrees {it['agreement']:.1%}; CAGR close {it['close_signal']['cagr']:.1%} vs live {it['live_signal']['cagr']:.1%}")
    return out


# ------------------------------------------------------------------ test 4
def test4(series, pub):
    R = pd.concat([pub.rename("published")] + [s.rename(f"c{i}") for i, s in series.items()], axis=1)
    R = R[R.index >= FULL].dropna(how="all")
    years = sorted(set(R.index.year))[3:]
    out = {}
    for mode, lb in (("expanding", None), ("trailing 3 years", 3)):
        st, picks = [], []
        for y in years:
            h = R[R.index.year < y]
            if lb: h = h[h.index.year >= y - lb]
            sh = h.mean() / h.std()
            best = sh.idxmax()
            st.append(R.loc[R.index.year == y, best])
            picks.append({"year": y, "picked": best, "published_rank": int((sh > sh["published"]).sum()) + 1, "of": R.shape[1]})
        wf = pd.concat(st)
        med = float(np.median([E.stats(R.loc[R.index.year >= years[0], c])["cagr"] for c in R.columns[1:]]))
        g = (1 + wf).cumprod(); gp = (1 + R.loc[wf.index, "published"]).cumprod()
        out[mode] = {"walk_forward": S(wf, str(years[0])), "published_same_years": S(R["published"], str(years[0])),
                     "median_candidate_same_years": med, "picks": picks,
                     "wf_oos": S(wf, str(years[0]), OOS_END), "wf_in": S(wf, IN_START),
                     "growth": {"dates": [d.strftime("%Y-%m-%d") for d in wf.index[::5]],
                                "wf": list(np.round(g.to_numpy()[::5], 4)), "pub": list(np.round(gp.to_numpy()[::5], 4))}}
        o = out[mode]
        print(f"[4] {mode:16} {years[0]}-2026: WF {o['walk_forward']['cagr']:.1%} (MDD {o['walk_forward']['mdd']:.1%}) vs published {o['published_same_years']['cagr']:.1%}; median candidate {med:.1%}")
    return out


# ------------------------------------------------------------------ test 5
def test5(inp):
    m = (inp.index >= "2002-06-01")
    spx_r = pd.Series(inp.spx).pct_change().to_numpy()[m]
    ratio_r = pd.Series(inp.ratio).pct_change().to_numpy()[m]
    level = inp.level[m]
    L = inp.leg_matrix()[m]; xlp = inp.legs["XLP"].to_numpy(float)[m]; ief = inp.legs["IEF"].to_numpy(float)[m]
    spx_tr = inp.legs["SPX"].to_numpy(float)[m]; qld = inp.legs["QLD"].to_numpy(float)[m]
    n = m.sum() - 1; warm = 300
    rows = []
    idx = pd.RangeIndex(n + warm)
    for k in range(N_BOOT):
        st = RNG.integers(1, n - BLOCK, size=(n + warm) // BLOCK + 1)
        ix = np.concatenate([np.arange(s, s + BLOCK) for s in st])[: n + warm]
        spx = 100 * np.cumprod(1 + spx_r[ix]); ratio = np.cumprod(1 + ratio_r[ix])
        # inputs object stand-in: temporarily point the engine at the path
        code = inp.regimes(E.PUBLISHED, spx=spx, ratio=ratio, level=level[ix].copy())
        sub = E.Inputs.__new__(E.Inputs); sub.index = idx
        r = E.Inputs.returns(sub, code, legs=L[ix], xlp_ief=(xlp[ix], ief[ix])).to_numpy()[warm:]
        rows.append({"s": E.stats(pd.Series(r)), "spy": E.stats(pd.Series(spx_tr[ix][warm:])), "qld": E.stats(pd.Series(qld[ix][warm:]))})
    a = lambda who, k: np.array([x[who][k] for x in rows])
    out = {who: {k: {p: float(np.nanpercentile(a(who, k), p)) for p in (5, 25, 50, 75, 95)} for k in ("cagr", "mdd", "sharpe")} for who in ("s", "spy", "qld")}
    out["p_beats_spy_cagr"] = float((a("s", "cagr") > a("spy", "cagr")).mean())
    out["p_beats_spy_sharpe"] = float((a("s", "sharpe") > a("spy", "sharpe")).mean())
    out["p_beats_qld_sharpe"] = float((a("s", "sharpe") > a("qld", "sharpe")).mean())
    out["p_mdd_worse_40"] = float((a("s", "mdd") < -0.4).mean())
    out["p_cagr_negative"] = float((a("s", "cagr") < 0).mean())
    out["paths"] = [{"s": x["s"]["cagr"], "q": x["spy"]["cagr"], "sm": x["s"]["mdd"]} for x in rows]
    s = out["s"]
    print(f"[5] IC CAGR median {s['cagr'][50]:.1%} (5-95% {s['cagr'][5]:.1%}..{s['cagr'][95]:.1%}); MDD median {s['mdd'][50]:.1%}; "
          f"beats SPY CAGR {out['p_beats_spy_cagr']:.0%}, Sharpe {out['p_beats_spy_sharpe']:.0%}; beats QLD Sharpe {out['p_beats_qld_sharpe']:.0%}; MDD<-40% {out['p_mdd_worse_40']:.0%}")
    return out


def main():
    t0 = time.time()
    inp = E.Inputs()
    res = {"validation": E.validate(inp), "published_params": asdict(E.PUBLISHED),
           "windows": {"full": FULL, "in": IN_START, "oos_end": OOS_END, "published": PUB_DATE}}
    print("[0]", res["validation"])
    res["test1"] = test1(inp)
    res["test2"], series, pub = test2(inp)
    res["test3"] = test3(inp)
    res["test4"] = test4(series, pub)
    res["test5"] = test5(inp)
    res["as_of"] = str(inp.index[-1].date())
    (HERE / "results.json").write_text(json.dumps(res, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
