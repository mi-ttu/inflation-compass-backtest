"""Levered Compass -- Monthly (QLD/ERX): same as simulate_levered_monthly.py
but QLD (ProShares Ultra QQQ, 2x Nasdaq-100) replaces XLK instead of TECL.
ERX (Direxion 2x energy) still replaces XLE. Utilities and the
disinflationary-slowdown blend are unchanged.

QLD launched 2006-06-21; ERX launched 2008-11-19 (the later, binding date).

Usage: .venv/Scripts/python.exe backtest/simulate_levered_monthly_qld_erx.py
"""
from _levered_common import run_variant

HOLDING_SUBSTITUTION = {"XLE": "ERX", "XLK": "QLD"}

if __name__ == "__main__":
    run_variant("Levered Compass -- Monthly (QLD/ERX)", HOLDING_SUBSTITUTION, "levered_monthly_qld_erx_returns.csv")
