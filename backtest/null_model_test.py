"""Null-model / block-permutation robustness test for the Unlevered
Extended strategy.

Question: does the strategy's edge come from genuine regime-timing skill,
or simply from holding trending sector ETFs (XLE/XLK/XLU/XLP+IEF) most of
the time, regardless of WHEN each one was held?

Method (block permutation): the actual sequence of monthly holding periods
is grouped into BLOCKS -- consecutive months holding the same asset. This
fixes, exactly as observed:
    - the total number of trades (block count - 1)
    - the holding-period-length distribution
    - the total number of months held in each asset
For each of N_SIMULATIONS random draws, the ORDER of these blocks is
shuffled and laid down across the same fixed sequence of monthly calendar
slots. Each slot's realized return then comes from the REAL market return
of whichever asset the shuffle assigns to it, on that slot's REAL
(unchanged) calendar dates -- i.e. the same assets, same total months held,
same turnover, only WHICH CALENDAR MONTH each asset was held in is
randomized. If the actual (unshuffled) strategy beats the large majority of
random shuffles, that's evidence the specific timing is adding value beyond
just holding trending sectors in some order; if it sits in the middle of
the null distribution, the timing isn't demonstrably doing anything a random
reordering wouldn't.

Simplification for tractability: the XLP+IEF disinflationary-slowdown
quadrant is treated here as a DAILY-rebalanced 50/50 blend (0.5*XLP +
0.5*IEF every day) rather than this project's usual buy-and-hold-and-drift-
until-next-rebalance convention. A buy-and-hold blend is path-dependent on
its OWN rebalance date, which would change under shuffling and defeat
vectorization; daily rebalancing has no such dependency and is a
sub-basis-point-level approximation for two assets of this volatility over
a few weeks. Verified below by checking the unshuffled reconstruction
against the already-published Unlevered Extended stats before trusting the
shuffled results.

Usage: .venv/Scripts/python.exe backtest/null_model_test.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from simulate_extended_monthly import spliced_series

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")
N_SIMULATIONS = 5000
RANDOM_SEED = 20260821
TRADING_DAYS_PER_YEAR = 252

ASSET_LABELS = ["XLE", "XLK", "XLU", "XLP+IEF_5050"]


def build_period_map(con: duckdb.DuckDBPyConnection):
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    xle = spliced_series(con, "XLE")
    xlk = spliced_series(con, "XLK")
    xlu = spliced_series(con, "XLU")
    xlp = spliced_series(con, "XLP")
    ief = spliced_series(con, "IEF")
    blend = (0.5 * xlp + 0.5 * ief).dropna()  # daily-rebalanced (see module docstring)

    asset_returns = {"XLE": xle, "XLK": xlk, "XLU": xlu, "XLP+IEF_5050": blend}
    all_dates = xle.index

    periods = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        label = regime.loc[i, "holding"]
        dates = all_dates[(all_dates > start) & (all_dates <= end)]
        if len(dates) == 0:
            continue
        periods.append({"start": start, "end": end, "label": label, "dates": dates})

    return periods, asset_returns


def compute_stats(returns: np.ndarray) -> dict:
    equity = np.cumprod(1 + returns)
    n_years = len(returns) / TRADING_DAYS_PER_YEAR
    cagr = equity[-1] ** (1 / n_years) - 1
    vol = returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    ann_return = returns.mean() * TRADING_DAYS_PER_YEAR
    sharpe = ann_return / vol if vol else np.nan
    running_max = np.maximum.accumulate(equity)
    dd = equity / running_max - 1
    maxdd = dd.min()
    calmar = cagr / abs(maxdd) if maxdd else np.nan
    return {"cagr": cagr, "vol": vol, "sharpe": sharpe, "maxdd": maxdd, "calmar": calmar, "growth": equity[-1]}


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    periods, asset_returns = build_period_map(con)
    con.close()

    periods = [p for p in periods if p["end"] >= REPORT_START]
    if periods and periods[0]["start"] < REPORT_START:
        periods[0]["dates"] = periods[0]["dates"][periods[0]["dates"] > REPORT_START]

    all_dates = pd.DatetimeIndex(sorted(set().union(*[p["dates"] for p in periods])))
    # Restrict to dates every asset series actually has data for -- e.g. a
    # single isolated data-vendor gap (2026-07-22 in the IEF/XLP blend) would
    # otherwise inject one NaN that numpy's cumprod (unlike pandas) does not
    # skip, silently wiping out every simulation that happens to land that
    # asset on that day.
    for lab in ASSET_LABELS:
        dropped = all_dates.difference(asset_returns[lab].index)
        if len(dropped):
            print(f"Dropping {len(dropped)} date(s) missing from {lab}: {dropped.tolist()}")
        all_dates = all_dates.intersection(asset_returns[lab].index)
    n_days = len(all_dates)
    day_index = {d: i for i, d in enumerate(all_dates)}

    label_idx = {lab: i for i, lab in enumerate(ASSET_LABELS)}
    R = np.zeros((n_days, len(ASSET_LABELS)))
    for lab in ASSET_LABELS:
        R[:, label_idx[lab]] = asset_returns[lab].reindex(all_dates).values

    period_idx_for_day = np.zeros(n_days, dtype=int)
    orig_labels = []
    for p_i, p in enumerate(periods):
        for d in p["dates"]:
            if d in day_index:
                period_idx_for_day[day_index[d]] = p_i
        orig_labels.append(p["label"])
    n_periods = len(periods)
    orig_label_ids = np.array([label_idx[l] for l in orig_labels])

    # ---- sanity check: unshuffled reconstruction vs already-published stats ----
    actual_asset_idx = orig_label_ids[period_idx_for_day]
    actual_returns = R[np.arange(n_days), actual_asset_idx]
    actual = compute_stats(actual_returns)
    print("Sanity check -- unshuffled reconstruction vs published Unlevered Extended stats:")
    print(f"  CAGR {actual['cagr']:.2%} (published 19.8%)  MaxDD {actual['maxdd']:.1%} (published -38.9%)  Sharpe {actual['sharpe']:.2f} (published 1.04)")
    print()

    # ---- blocks: consecutive periods sharing the same label ----
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < n_periods:
        j = i
        while j < n_periods and orig_label_ids[j] == orig_label_ids[i]:
            j += 1
        blocks.append((int(orig_label_ids[i]), j - i))
        i = j
    print(f"{n_periods} monthly periods -> {len(blocks)} holding blocks ({len(blocks) - 1} trades)")
    print()

    rng = np.random.default_rng(RANDOM_SEED)
    day_arange = np.arange(n_days)
    null_rows = []
    for _ in range(N_SIMULATIONS):
        order = rng.permutation(len(blocks))
        shuffled_label_ids = np.empty(n_periods, dtype=int)
        pos = 0
        for b_i in order:
            label_id, count = blocks[b_i]
            shuffled_label_ids[pos:pos + count] = label_id
            pos += count
        asset_idx_for_day = shuffled_label_ids[period_idx_for_day]
        sim_returns = R[day_arange, asset_idx_for_day]
        null_rows.append(compute_stats(sim_returns))

    null_df = pd.DataFrame(null_rows)
    report(actual, null_df)

    out_path = PROJECT_ROOT / "backtest" / "null_model_distribution.csv"
    null_df.to_csv(out_path, index=False)
    print(f"\nSaved {N_SIMULATIONS} null-simulation stats to {out_path}")


def report(actual: dict, null_df: pd.DataFrame) -> None:
    print(f"Null-model distribution across {len(null_df)} random block-order permutations:")
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(null_df.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).T)
    print()

    def pct_beats(metric: str, higher_is_better: bool = True) -> float:
        if higher_is_better:
            return float((null_df[metric] <= actual[metric]).mean())
        return float((null_df[metric] >= actual[metric]).mean())

    print("Actual (unshuffled) strategy vs. the null distribution:")
    print(f"  CAGR:    actual {actual['cagr']:.2%}   null median {null_df['cagr'].median():.2%}   "
          f"actual beats {pct_beats('cagr'):.1%} of random shuffles")
    print(f"  Sharpe:  actual {actual['sharpe']:.2f}   null median {null_df['sharpe'].median():.2f}   "
          f"actual beats {pct_beats('sharpe'):.1%} of random shuffles")
    print(f"  MaxDD:   actual {actual['maxdd']:.1%}   null median {null_df['maxdd'].median():.1%}   "
          f"actual beats (less negative than) {pct_beats('maxdd', higher_is_better=True):.1%} of random shuffles")
    print(f"  Calmar:  actual {actual['calmar']:.2f}   null median {null_df['calmar'].median():.2f}   "
          f"actual beats {pct_beats('calmar'):.1%} of random shuffles")
    print(f"  Growth of $1: actual ${actual['growth']:,.0f}   null median ${null_df['growth'].median():,.0f}   "
          f"actual beats {pct_beats('growth'):.1%} of random shuffles")


if __name__ == "__main__":
    main()
