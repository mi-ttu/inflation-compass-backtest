"""Levered Compass -- Monthly (TECL/ERX): same regime signal, same
month-end decision cadence as the original Inflation Compass Model, but
TECL (Direxion 3x tech) is held in place of XLK, and ERX (Direxion 2x
energy) is held in place of XLE. Utilities (XLU) and the
disinflationary-slowdown blend (XLP + IEF, 50/50) are unchanged.

See backtest/_levered_common.py for the shared simulation logic and the
"signal on the unleveraged benchmark, trade the leveraged instrument"
rationale (same pattern as TradeDesk's MaxAlpha strategy).

TECL launched 2008-12-30 and ERX launched 2008-11-19, so this backtest is
restricted to 2008-12-30 onward -- missing 2003-2008 entirely.

Usage: .venv/Scripts/python.exe backtest/simulate_levered_monthly.py
"""
from _levered_common import run_variant

HOLDING_SUBSTITUTION = {"XLE": "ERX", "XLK": "TECL"}

if __name__ == "__main__":
    run_variant("Levered Compass -- Monthly (TECL/ERX)", HOLDING_SUBSTITUTION, "levered_monthly_returns.csv")
