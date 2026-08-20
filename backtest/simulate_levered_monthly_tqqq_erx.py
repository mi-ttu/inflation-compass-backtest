"""Levered Compass -- Monthly (TQQQ/ERX): same as simulate_levered_monthly.py
but TQQQ (ProShares UltraPro QQQ, 3x Nasdaq-100) replaces XLK instead of
TECL. ERX (Direxion 2x energy) still replaces XLE. Utilities and the
disinflationary-slowdown blend are unchanged.

TQQQ launched 2010-02-11 -- later than both TECL and ERX -- so this is the
shortest-window variant of the three, starting 2010-02-11.

Usage: .venv/Scripts/python.exe backtest/simulate_levered_monthly_tqqq_erx.py
"""
from _levered_common import run_variant

HOLDING_SUBSTITUTION = {"XLE": "ERX", "XLK": "TQQQ"}

if __name__ == "__main__":
    run_variant("Levered Compass -- Monthly (TQQQ/ERX)", HOLDING_SUBSTITUTION, "levered_monthly_tqqq_erx_returns.csv")
