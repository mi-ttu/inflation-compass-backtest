"""Live tracking vs backtest, for the dashboard's "Live tracking" card.

From LIVE_START on, a strategy's model returns are out-of-sample data the
backtest never saw. For each tracked series this computes:
  - bands: percentiles (5/25/50/75/95) of cumulative growth over every
    historical window of 1..HORIZON trading days before LIVE_START
  - live: cumulative growth since LIVE_START
  - percentile: where the live result sits among historical windows of the
    same length
These are model returns, not brokerage fills, so slippage and missed trades
don't show up here.

Identical copies live in max-alpha-backtest/backtest/ and
inflation-compass-backtest/backtest/ (each dashboard ships standalone).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LIVE_START = "2026-10-01"
HORIZON = 756  # trading days (~3 years)
QUANTILES = (5, 25, 50, 75, 95)


def build(series: dict[str, pd.Series], start: str = LIVE_START, horizon: int = HORIZON) -> dict:
    """series: {key: daily returns indexed by trading date}, all on one calendar."""
    frame = pd.concat(series, axis=1).dropna()
    frame.index = pd.to_datetime(frame.index)
    hist, live = frame[frame.index < start], frame[frame.index >= start]
    out = {"start": start, "horizon": horizon, "live_dates": [d.strftime("%Y-%m-%d") for d in live.index], "series": {}}
    for key in frame.columns:
        cum = np.concatenate([[0.0], np.cumsum(np.log1p(hist[key].to_numpy(float)))])
        bands = {q: [] for q in QUANTILES}
        for h in range(1, horizon + 1):
            for q, v in zip(QUANTILES, np.percentile(cum[h:] - cum[:-h], QUANTILES)):
                bands[q].append(round(float(np.exp(v)), 4))
        growth = np.cumprod(1 + live[key].to_numpy(float)) if len(live) else np.array([])
        pct = None
        if len(live):
            h = min(len(live), horizon)
            pct = float(((cum[h:] - cum[:-h]) < np.log(growth[h - 1])).mean())
        out["series"][key] = {"bands": bands, "live": [round(float(v), 5) for v in growth], "percentile": pct}
    return out
