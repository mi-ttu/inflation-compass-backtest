"""Hybrid (QLD goldilocks / XLE reflation), Daily, 2-day regime confirmation:
a tested variant of simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal.py,
NOT part of Varadi's published rules.

Rule change: the daily regime must read the same on two consecutive closes
before the holding switches (a new regime seen on only one close is ignored).
Everything else -- signals (signals_daily_extended), regime -> holding map,
QLD substitution, drifting 50/50 XLP+IEF, 1-day implementation lag -- is
identical to the daily-signal variant.

Why: the daily variant whipsaws between QLD and XLE when the inflation signal
sits near its boundary (~11 trades/yr, 44% of holdings last 1-3 days). See
robustness/confirm_regime_test.py and section 6 of robustness/report.html:
the rule cuts trading to ~7/yr and helps once trading costs are included,
but is about neutral with no costs and was designed after seeing this data.

Usage: .venv/Scripts/python.exe backtest/simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal_confirm2.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_levered_monthly import spliced_series_unlevered
from simulate_extended_monthly import load_real_total_return
from simulate_hybrid_qld_goldilocks_xle_reflation import build_qld_extended
from simulate_hybrid_qld_goldilocks_xle_reflation_daily_signal import REGIME_MAP, REPORT_START, SUBSTITUTION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
CONFIRM_DAYS = 2


def confirmed(raw: list[str], k: int) -> list[str]:
    """The regime only changes once the raw regime has held k consecutive days."""
    out, cur, run = [], raw[0], 1
    for i, r in enumerate(raw):
        if i:
            run = run + 1 if r == raw[i - 1] else 1
        if r != cur and run >= k:
            cur = r
        out.append(cur)
    return out


def build_daily_exposure(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    signals = con.execute(
        "SELECT trading_date, growth_up, inflation_on FROM signals_daily_extended ORDER BY trading_date"
    ).df()
    signals["trading_date"] = pd.to_datetime(signals["trading_date"])
    signals = signals.dropna(subset=["growth_up", "inflation_on"]).reset_index(drop=True)
    # growth_up is False (not null) during the 200-day SMA warmup, exactly as
    # the published variant treats it; confirmation runs over the same rows.
    raw = [REGIME_MAP[(bool(g), bool(i))][0] for g, i in zip(signals["growth_up"], signals["inflation_on"], strict=True)]
    signals["regime"] = confirmed(raw, CONFIRM_DAYS)
    holding = {v[0]: v[1] for v in REGIME_MAP.values()}
    signals["traded_holding"] = signals["regime"].map(holding).map(lambda h: SUBSTITUTION.get(h, h))
    signals["exposure_holding"] = signals["traded_holding"].shift(1)
    signals = signals.dropna(subset=["exposure_holding"]).reset_index(drop=True)
    return signals[signals["trading_date"] >= REPORT_START].reset_index(drop=True)


def simulate(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    exposure = build_daily_exposure(con)
    series = {
        "QLD": build_qld_extended(con),
        "XLE": spliced_series_unlevered(con, "XLE"),
        "XLU": spliced_series_unlevered(con, "XLU"),
        "XLP": spliced_series_unlevered(con, "XLP"),
        "IEF": spliced_series_unlevered(con, "IEF"),
    }
    gspc = load_real_total_return(con, "^GSPC")
    exposure["run_id"] = (exposure["exposure_holding"] != exposure["exposure_holding"].shift(1)).cumsum()
    frames = []
    for _, grp in exposure.groupby("run_id"):
        holding = grp["exposure_holding"].iloc[0]
        dates = pd.DatetimeIndex(grp["trading_date"])
        if holding == "XLP+IEF_5050":
            nav = 0.5 * (1.0 + series["XLP"].reindex(dates)).cumprod() + 0.5 * (1.0 + series["IEF"].reindex(dates)).cumprod()
            model_ret = nav / nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = series[holding].reindex(dates)
        frames.append(pd.DataFrame({"trading_date": dates, "traded_holding": holding,
                                    "model_return": model_ret.to_numpy(), "spy_return": gspc.reindex(dates).to_numpy()}))
    return pd.concat(frames).sort_values("trading_date").reset_index(drop=True)


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    daily = simulate(con)
    con.close()
    n_switches = int((daily["traded_holding"] != daily["traded_holding"].shift(1)).sum())
    print(f"Hybrid (QLD/XLE), Daily, {CONFIRM_DAYS}-day confirmation: {len(daily)} trading days, "
          f"{daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}, "
          f"{n_switches / (len(daily) / 252):.1f} holding changes per year")
    stats = perf_stats(daily["model_return"], daily["trading_date"])
    print(pd.Series(stats).to_string())
    out_path = PROJECT_ROOT / "backtest" / "hybrid_qld_goldilocks_xle_reflation_daily_signal_confirm2_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
