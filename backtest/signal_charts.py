"""Per-signal status charts for the daily status email, in the style of the
MaxAlpha backtest project's: each input signal over the last ~3 months
against its threshold (or reference line), with the background shaded by the
holding decided that day. Four inputs drive the regime:

  Growth             S&P 500 vs its 200-day average
  Inflation level    5-year breakeven vs the 2.0% target
  Inflation momentum 5-year breakeven vs its value 60 trading days earlier
  Sector momentum    cyclicals-vs-defensives ratio's 60-day trend slope

  inflation signal = level AND (momentum OR sector momentum)

Email clients don't run JavaScript or reliably render inline SVG, so each
chart is a PNG the email embeds as an inline (cid:) image.

Not meant to be run standalone -- called from notify.py with the `history`
frame live_preview.build_preview() returns.
"""
import io
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: the scheduled task has no display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transform"))
import build_signals_extended as bse  # noqa: E402

LINE = "#171a24"
REF = "#d81bd8"
GRID = "#e6e9f1"
TEXT = "#5b6272"
WINDOW = bse.MOMENTUM_WINDOW_DAYS


def _trend(ratio: np.ndarray) -> np.ndarray:
    """The OLS line the sector-momentum slope is read from: fitted over the
    last WINDOW points, NaN before that."""
    out = np.full(len(ratio), np.nan)
    y = ratio[-WINDOW:]
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1)
    out[-WINDOW:] = intercept + slope * x
    return out


def _specs(hist: pd.DataFrame, inflation_as_of: str) -> list[dict]:
    last = hist.iloc[-1]
    spx, sma = float(last["spy_close"]), float(last["spy_sma_200"])
    be, lag = float(last["inflation_level"]), float(last["breakeven_lagged"])
    target = float(bse.BREAKEVEN_TARGET)
    ratio = hist["sector_basket_ratio"].to_numpy(float)
    ratio = ratio / ratio[0] * 100.0
    trend = _trend(ratio)
    slope_pct = float(np.polyfit(np.arange(WINDOW), ratio[-WINDOW:], 1)[0] / ratio[-WINDOW:].mean() * 100.0)
    rel = lambda a, b: ">" if a > b else "<"  # noqa: E731
    return [
        dict(key="growth", title=f"Growth: S&P 500 above its {bse.SMA_WINDOW}-day average", state=bool(last["growth_up"]),
             y=hist["spy_close"].to_numpy(float), ref=hist["spy_sma_200"].to_numpy(float), fmt=lambda v: f"{v:,.0f}",
             text=f"S&P 500 {spx:,.2f} {rel(spx, sma)} {bse.SMA_WINDOW}-day average {sma:,.2f} ({spx / sma - 1:+.1%})"),
        dict(key="level", title=f"Inflation level: 5-year breakeven above {target:.1f}%", state=bool(last["breakeven_above_target"]),
             y=hist["inflation_level"].to_numpy(float), ref=np.full(len(hist), target), fmt=lambda v: f"{v:.2f}%",
             text=f"5y breakeven {be:.2f}% {rel(be, target)} {target:.2f}% target (latest FRED value, {inflation_as_of})"),
        dict(key="momentum", title=f"Inflation momentum: breakeven above its level {WINDOW} days ago", state=bool(last["breakeven_momentum_up"]),
             y=hist["inflation_level"].to_numpy(float), ref=hist["breakeven_lagged"].to_numpy(float), fmt=lambda v: f"{v:.2f}%",
             text=f"5y breakeven {be:.2f}% vs {lag:.2f}% {WINDOW} trading days earlier ({be - lag:+.2f} pts)"),
        dict(key="sector", title=f"Sector momentum: cyclicals vs defensives, {WINDOW}-day trend up", state=bool(last["asset_momentum_up"]),
             y=ratio, ref=trend, fmt=lambda v: f"{v:.1f}",
             text=f"Cyclicals/defensives ratio (rebased to 100): {WINDOW}-day trend {slope_pct:+.3f}% per day"),
    ]


def _chart_png(spec: dict, hist: pd.DataFrame, holding_colors: dict) -> bytes:
    n = len(hist)
    x = np.arange(n)
    y, ref = spec["y"], spec["ref"]

    fig, ax = plt.subplots(figsize=(6.0, 2.35), dpi=120)
    holdings = hist["holding"].tolist()
    start = 0
    for i in range(1, n + 1):
        if i == n or holdings[i] != holdings[start]:
            ax.axvspan(start - 0.5, i - 0.5, color=holding_colors.get(holdings[start], "#999999"), alpha=0.16, lw=0)
            start = i
    ax.plot(x, ref, color=REF, lw=1.8)
    ax.plot(x, y, color=LINE, lw=1.7)
    ax.plot([x[-1]], [y[-1]], "o", color=LINE, ms=4.5)

    values = np.concatenate([y, ref[np.isfinite(ref)]])
    pad = (values.max() - values.min()) * 0.12 or abs(values.max()) * 0.05 or 1.0
    ax.set_ylim(values.min() - pad, values.max() + pad)
    ax.set_xlim(-0.5, n - 0.5)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: spec["fmt"](v)))
    ticks = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})
    dates = pd.to_datetime(hist["trading_date"]).tolist()
    ax.set_xticks(ticks, [f"{dates[i].month}/{dates[i].day}" for i in ticks])
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT, labelsize=8.5, length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def render_signal_charts(history: pd.DataFrame, holding_colors: dict, inflation_as_of: str) -> list[dict]:
    """One entry per signal: key, title, state (bool), text (value vs its
    reference), png (bytes)."""
    hist = history.reset_index(drop=True)
    return [{"key": s["key"], "title": s["title"], "state": s["state"], "text": s["text"],
             "png": _chart_png(s, hist, holding_colors)} for s in _specs(hist, inflation_as_of)]
