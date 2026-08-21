"""Moving-block-bootstrap significance test for the Unlevered Extended
strategy's Sharpe ratio and its outperformance over SPY.

A naive Sharpe-ratio significance test assumes returns are i.i.d. This
strategy's returns are not: it holds one position for weeks to months at a
time, so consecutive daily returns share the same regime and are
autocorrelated. That understates the true sampling uncertainty if ignored.

Method: moving block bootstrap. Resample overlapping blocks of L
consecutive trading days (with replacement) from the actual daily return
history, concatenating blocks until a resampled series of the same total
length is built, for B random draws. Blocks preserve local
autocorrelation/regime-persistence structure that day-by-day shuffling
would destroy. Two block lengths are tested (~1 month, ~1 quarter) to check
the result isn't an artifact of the block-length choice.

Paired resampling: the strategy and SPY are resampled using the SAME
random block-start indices on each draw, preserving their day-by-day joint
correlation -- this is what lets the test isolate whether the strategy's
OUTPERFORMANCE over SPY (Sharpe_strategy - Sharpe_SPY) is statistically
distinguishable from zero, not just whether the strategy's own Sharpe is
positive (which a levered/volatile-but-lucky series could also show).

Usage: .venv/Scripts/python.exe backtest/significance_test.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
N_BOOTSTRAP = 5000
BLOCK_LENGTHS = [21, 63]  # ~1 month, ~1 quarter of trading days
TRADING_DAYS_PER_YEAR = 252
RANDOM_SEED = 20260821


def moving_block_bootstrap_indices(n: int, block_len: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = int(np.ceil(n / block_len))
    starts = rng.integers(0, n - block_len + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block_len) for s in starts])
    return idx[:n]


def sharpe(returns: np.ndarray) -> float:
    vol = returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    ann_return = returns.mean() * TRADING_DAYS_PER_YEAR
    return ann_return / vol if vol else np.nan


def cagr(returns: np.ndarray) -> float:
    equity = np.cumprod(1 + returns)
    n_years = len(returns) / TRADING_DAYS_PER_YEAR
    return equity[-1] ** (1 / n_years) - 1


def main() -> None:
    df = pd.read_csv(PROJECT_ROOT / "backtest" / "extended_monthly_returns.csv", parse_dates=["trading_date"])
    strat = df["model_return"].to_numpy()
    spy = df["spy_return"].to_numpy()
    n = len(strat)

    actual_sharpe = sharpe(strat)
    actual_spy_sharpe = sharpe(spy)
    actual_diff = actual_sharpe - actual_spy_sharpe
    actual_cagr = cagr(strat)

    print(f"Unlevered Extended, {n} trading days ({df['trading_date'].min().date()} -> {df['trading_date'].max().date()})")
    print(f"Point estimates: Sharpe {actual_sharpe:.2f}  (SPY {actual_spy_sharpe:.2f})  CAGR {actual_cagr:.2%}")
    print()

    for block_len in BLOCK_LENGTHS:
        rng = np.random.default_rng(RANDOM_SEED)
        boot_sharpes = np.empty(N_BOOTSTRAP)
        boot_diffs = np.empty(N_BOOTSTRAP)
        boot_cagrs = np.empty(N_BOOTSTRAP)
        for i in range(N_BOOTSTRAP):
            idx = moving_block_bootstrap_indices(n, block_len, rng)
            r_strat, r_spy = strat[idx], spy[idx]
            s = sharpe(r_strat)
            boot_sharpes[i] = s
            boot_diffs[i] = s - sharpe(r_spy)
            boot_cagrs[i] = cagr(r_strat)

        months = block_len / 21
        print(f"--- Block length {block_len} trading days (~{months:.1f} months) ---")
        print(f"Sharpe:  actual {actual_sharpe:.2f}   95% CI [{np.percentile(boot_sharpes, 2.5):.2f}, {np.percentile(boot_sharpes, 97.5):.2f}]   "
              f"P(Sharpe <= 0) = {(boot_sharpes <= 0).mean():.4f}")
        print(f"CAGR:    actual {actual_cagr:.2%}   95% CI [{np.percentile(boot_cagrs, 2.5):.2%}, {np.percentile(boot_cagrs, 97.5):.2%}]")
        print(f"Sharpe outperformance vs SPY: actual {actual_diff:.2f}   95% CI [{np.percentile(boot_diffs, 2.5):.2f}, {np.percentile(boot_diffs, 97.5):.2f}]   "
              f"P(no outperformance, diff <= 0) = {(boot_diffs <= 0).mean():.4f}")
        print()

        out = pd.DataFrame({"sharpe": boot_sharpes, "cagr": boot_cagrs, "sharpe_vs_spy_diff": boot_diffs})
        out.to_csv(PROJECT_ROOT / "backtest" / f"bootstrap_block{block_len}.csv", index=False)


if __name__ == "__main__":
    main()
