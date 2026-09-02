"""Inflation Compass -- Hybrid, Monthly (1990+): UPRO (ProShares UltraPro
S&P 500, 3x) replaces XLK in goldilocks; reflation stays unlevered real/
spliced XLE; XLU / XLP+IEF are untouched. Same "lever only one regime"
family as the QLD/XLE and TQQQ/XLE hybrids.

Worth flagging explicitly: this is a different kind of substitution than
every other goldilocks leverage variant tested so far. QQQ/TQQQ/QLD all
track ^NDX (Nasdaq-100) -- a tech-heavy but still sector-flavored bet,
directionally consistent with what XLK (GICS tech) represents. UPRO tracks
^GSPC (the S&P 500) -- broad market beta, no tech tilt at all. So this
variant isn't "more/less leverage on the same tech bet" like the QLD/TQQQ
comparison was; it's a genuinely different economic bet during goldilocks
(leveraged market beta instead of leveraged tech).

UPRO launched 2009-06-25. Extended back to 1990 with a synthetic
3x-daily-compounded ^GSPC proxy pre-inception -- exact by construction,
same reasoning already used for TQQQ's 3x ^NDX proxy, via the project's
generic spliced_leveraged_series() helper.

The synthetic UPRO segment carries no expense ratio / daily financing
cost, so it's a mild optimistic upper bound relative to a real fund, on
top of the volatility-decay effects daily compounding does capture.

Usage: .venv/Scripts/python.exe backtest/simulate_hybrid_upro_goldilocks_xle_reflation.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from _levered_common import perf_stats
from simulate_extended_levered_monthly import spliced_leveraged_series, spliced_series_unlevered
from simulate_extended_monthly import load_real_total_return

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
REPORT_START = pd.Timestamp("1990-01-01")
UPRO_LEVERAGE = 3


def build_upro_extended(con: duckdb.DuckDBPyConnection) -> pd.Series:
    gspc = load_real_total_return(con, "^GSPC")
    return spliced_leveraged_series(con, "UPRO", gspc, UPRO_LEVERAGE)


def build_daily_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    regime = con.execute(
        "SELECT decision_date, holding FROM regime_history_extended ORDER BY decision_date"
    ).df()
    regime["decision_date"] = pd.to_datetime(regime["decision_date"])

    series = {
        "UPRO": build_upro_extended(con),
        "XLE": spliced_series_unlevered(con, "XLE"),
        "XLU": spliced_series_unlevered(con, "XLU"),
        "XLP": spliced_series_unlevered(con, "XLP"),
        "IEF": spliced_series_unlevered(con, "IEF"),
    }
    substitution = {"XLK": "UPRO"}
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

    print(f"Hybrid (UPRO goldilocks / XLE reflation) -- Monthly: {len(daily)} trading days, {daily['trading_date'].min().date()} -> {daily['trading_date'].max().date()}")
    print()
    print("Time in each traded holding:")
    print((daily["traded_holding"].value_counts() / len(daily) * 100).round(1).astype(str) + "%")
    print()

    model_stats = perf_stats(daily["model_return"], daily["trading_date"])
    spy_stats = perf_stats(daily["spy_return"], daily["trading_date"])
    stats_df = pd.DataFrame({"Hybrid (UPRO/XLE)": model_stats, "S&P 500 (^GSPC proxy)": spy_stats})
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print(stats_df)

    out_path = PROJECT_ROOT / "backtest" / "hybrid_upro_goldilocks_xle_reflation_returns.csv"
    daily.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
