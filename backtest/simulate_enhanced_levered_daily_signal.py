"""Enhanced, Levered, Daily (TQQQ/ERX) -- 2003+: combines the Enhanced
(ensembled 40/60/80-day momentum, see transform/build_signals_enhanced.py)
signal engine with daily-reactive cadence (checked every trading day,
rebalanced on any regime change, 1-day implementation lag) and the
TQQQ/ERX substitution + synthetic pre-inception leverage already built in
simulate_extended_levered_monthly.py (reused here, not reimplemented).

Real data only, no splice -- see simulate_enhanced_levered_monthly.py's
docstring for why the same execution-leg helpers are still correct here.

Usage: .venv/Scripts/python.exe backtest/simulate_enhanced_levered_daily_signal.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_levered_monthly import build_erx_extended, build_tqqq_extended
from simulate_extended_monthly import load_real_total_return
from simulate_extended_levered_monthly import spliced_series_unlevered

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("2003-01-01")

REGIME_MAP = {
    (True, True): ("reflation", "XLE"),
    (True, False): ("goldilocks", "XLK"),
    (False, True): ("stagflation", "XLU"),
    (False, False): ("disinflationary_slowdown", "XLP+IEF_5050"),
}
SUBSTITUTION = {"XLE": "ERX", "XLK": "TQQQ"}


def build_daily_exposure(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    signals = con.execute(
        "SELECT trading_date, growth_up, inflation_on FROM signals_daily_enhanced ORDER BY trading_date"
    ).df()
    signals["trading_date"] = pd.to_datetime(signals["trading_date"])
    signals = signals.dropna(subset=["growth_up", "inflation_on"]).reset_index(drop=True)
    mapped = [REGIME_MAP[(bool(g), bool(i))] for g, i in zip(signals["growth_up"], signals["inflation_on"], strict=True)]
    signals["regime"] = [m[0] for m in mapped]
    signals["original_holding"] = [m[1] for m in mapped]
    signals["traded_holding"] = signals["original_holding"].map(lambda h: SUBSTITUTION.get(h, h))

    # 1-day implementation lag, same convention as every other daily-signal variant.
    signals["exposure_holding"] = signals["traded_holding"].shift(1)
    signals = signals.dropna(subset=["exposure_holding"]).reset_index(drop=True)
    return signals[signals["trading_date"] >= REPORT_START].reset_index(drop=True)


def simulate(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    exposure = build_daily_exposure(con)

    series = {
        "TQQQ": build_tqqq_extended(con),
        "ERX": build_erx_extended(con),
        "XLU": spliced_series_unlevered(con, "XLU"),
        "XLP": spliced_series_unlevered(con, "XLP"),
        "IEF": spliced_series_unlevered(con, "IEF"),
    }
    gspc = load_real_total_return(con, "^GSPC")

    exposure["run_id"] = (exposure["exposure_holding"] != exposure["exposure_holding"].shift(1)).cumsum()

    rows = []
    for _, grp in exposure.groupby("run_id"):
        holding = grp["exposure_holding"].iloc[0]
        dates = pd.DatetimeIndex(grp["trading_date"])

        if holding == "XLP+IEF_5050":
            leg_xlp = (1.0 + series["XLP"].reindex(dates)).cumprod()
            leg_ief = (1.0 + series["IEF"].reindex(dates)).cumprod()
            nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = nav / nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = series[holding].reindex(dates)

        spy_ret = gspc.reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "traded_holding": holding,
                "model_return": model_ret.loc[dt], "spy_return": spy_ret.loc[dt],
            })

    return pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    daily = simulate(con)
    con.close()

    n_switches = int((daily["traded_holding"] != daily["traded_holding"].shift(1)).sum())
    n_days = len(daily)
    print(f"Enhanced, Levered, Daily (TQQQ/ERX): {n_days} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print(f"Holding changes (trades): {n_switches}  ({n_switches / (n_days / 252):.1f} per year)")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / n_days * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Enhanced, Levered, Daily (TQQQ/ERX)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "enhanced_levered_tqqq_erx_daily_signal_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
