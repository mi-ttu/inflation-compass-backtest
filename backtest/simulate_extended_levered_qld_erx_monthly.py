"""Inflation Compass -- Extended, Levered QLD/ERX (1990+): both legs
levered this time, matching the same signal engine as every other Extended
variant. QLD (2x Nasdaq-100) replaces XLK in goldilocks; ERX (2x energy)
replaces XLE in reflation -- same substitution pattern as the TQQQ/ERX
Extended Levered variant, half the goldilocks leverage. XLU / XLP+IEF are
unchanged from every unlevered variant already built.

Extends the project's existing shorter-window QLD/ERX variant
(simulate_levered_monthly_qld_erx.py, real data only from ERX's
2008-11-19 inception) back to 1990 with synthetic pre-inception proxies,
reusing what's already built rather than re-deriving it:
    - QLD pre-2006-06-21: build_qld_extended() from
      simulate_hybrid_qld_goldilocks_xle_reflation.py -- 2x-daily-compounded
      ^NDX (the index QLD tracks).
    - ERX pre-2008-11-19: build_erx_extended() from
      simulate_extended_levered_monthly.py -- 2x-daily-compounded
      [Fama-French Enrgy pre-1998, chained with real XLE 1998-2008].

Neither synthetic-leverage segment includes the expense ratio / daily
financing cost real leveraged ETFs carry -- so the pre-inception synthetic
portions are a mild optimistic upper bound relative to what an actual fund
would have delivered, on top of the volatility-decay effects that ARE
captured by daily compounding.

Usage: .venv/Scripts/python.exe backtest/simulate_extended_levered_qld_erx_monthly.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_levered_monthly import build_erx_extended, spliced_series_unlevered
from simulate_extended_monthly import load_real_total_return
from simulate_hybrid_qld_goldilocks_xle_reflation import build_qld_extended

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    series = {
        "QLD": build_qld_extended(con),
        "ERX": build_erx_extended(con),
        "XLU": spliced_series_unlevered(con, "XLU"),
        "XLP": spliced_series_unlevered(con, "XLP"),
        "IEF": spliced_series_unlevered(con, "IEF"),
    }
    substitution = {"XLE": "ERX", "XLK": "QLD"}
    gspc = load_real_total_return(con, "^GSPC")

    rows = []
    for i in range(len(regime) - 1):
        start, end = regime.loc[i, "decision_date"], regime.loc[i + 1, "decision_date"]
        original_holding = regime.loc[i, "holding"]
        traded_holding = substitution.get(original_holding, original_holding)
        dates = pd.DatetimeIndex([d for d in gspc.index if start < d <= end])

        if traded_holding == "XLP+IEF_5050":
            leg_xlp = (1 + series["XLP"].reindex(dates)).cumprod()
            leg_ief = (1 + series["IEF"].reindex(dates)).cumprod()
            period_nav = 0.5 * leg_xlp + 0.5 * leg_ief
            model_ret = period_nav / period_nav.shift(1).fillna(1.0) - 1.0
        else:
            model_ret = series[traded_holding].reindex(dates)

        spy_ret = gspc.reindex(dates)
        for dt in dates:
            rows.append({
                "trading_date": dt, "original_holding": original_holding, "traded_holding": traded_holding,
                "model_return": model_ret.loc[dt], "spy_return": spy_ret.loc[dt],
            })

    return pd.DataFrame(rows).sort_values("trading_date").reset_index(drop=True)


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    daily = build_daily_equity(con)
    con.close()

    daily = daily[daily["trading_date"] >= REPORT_START].reset_index(drop=True)

    print(f"Extended, Levered (QLD/ERX) -- Monthly: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Extended, Levered (QLD/ERX)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "extended_levered_qld_erx_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
