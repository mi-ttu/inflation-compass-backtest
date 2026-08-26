"""One-time setup for a fresh machine/clone: builds data/curated.duckdb from
scratch (it is git-ignored -- see README.md) and produces a fully current
interactive_chart.html.

Runs the steps refresh_chart.py does NOT cover because they only need to
happen once per machine: schema init, the NYSE trading calendar, and the
Fama-French industry-portfolios pull (used only for the pre-1998 splice and
essentially static). Everything else -- yfinance/FRED pulls, calendar
alignment, total-return reconciliation, the regime signal engine, and the
three backtest variants the chart displays -- is identical to a normal
refresh, so this script just runs its one-time steps and then delegates to
refresh_chart.py.

Usage: .venv/Scripts/python.exe backtest/bootstrap.py
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

ONE_TIME_STEPS = [
    "transform/init_db.py",
    "transform/build_trading_calendar.py",
    "ingest/fetch_famafrench.py",
]


def run(rel_path: str) -> None:
    script = PROJECT_ROOT / rel_path
    print(f"[bootstrap] running {rel_path} ...")
    result = subprocess.run([str(PYTHON), str(script)], cwd=str(script.parent))
    if result.returncode != 0:
        raise RuntimeError(f"{rel_path} exited with code {result.returncode} -- aborting bootstrap")


def main() -> None:
    db_path = PROJECT_ROOT / "data" / "curated.duckdb"
    if db_path.exists():
        print(f"[bootstrap] {db_path} already exists -- refusing to overwrite.")
        print("[bootstrap] delete it first if you really want a from-scratch rebuild,")
        print("[bootstrap] or just run refresh_chart.py for a normal incremental refresh.")
        sys.exit(1)

    for step in ONE_TIME_STEPS:
        run(step)

    print("[bootstrap] one-time setup done -- handing off to refresh_chart.py for the")
    print("[bootstrap] full historical data pull, signal engine, and backtests.")
    print()
    run("backtest/refresh_chart.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[bootstrap] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
