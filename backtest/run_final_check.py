"""OPTIONAL final-close check: emails ONLY if the final close changed the
allocation an intraday (e.g. 2:30 PM) run of run_daily.py recommended.

Not scheduled since 2026-10-29: the daily run itself now happens after the
close (3:05 PM Central) on final prices, which makes this check redundant.
Kept for anyone who goes back to an intraday daily run plus a final check, as
the MaxAlpha backtest project also did.

How it works: it waits for Yahoo's closing bars to settle (close_data.py),
refreshes, and compares the recommended holding with the one the daily run
saved (status_store.py). Same holding: nothing is sent (log only). Different,
or no baseline saved today: an alert goes out, flagged accordingly, and with a
warning if the closing prices never settled.

Usage: python.exe backtest/run_final_check.py
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_preview
import notify
import refresh_chart
import run_daily
import status_store
from close_data import ET, MARKET_CLOSE, wait_for_final_close


def main() -> None:
    today = date.today()
    if not run_daily.is_trading_day(today):
        print(f"[final_check] {today} is not an NYSE trading day -- nothing to do.")
        return
    if datetime.now(ET).time() < MARKET_CLOSE:
        print("[final_check] the market is still open (before 4 PM ET) -- the final close doesn't exist yet; exiting.")
        return

    data_final = wait_for_final_close(today, "[final_check]")
    refresh_chart.main()
    preview = live_preview.build_preview()
    refresh_chart.patch_signal_status(preview)  # dashboard's Signal status panel; never raises
    if preview["isLive"]:
        data_final = False  # today's bar still missing after the refresh: the preview fell back to live quotes
    baseline = status_store.load_baseline(today)
    final = preview["preview"]["holding"]

    if baseline and baseline["holding"] == final:
        print(f"[final_check] final close confirms the earlier allocation ({final}); no email sent.")
        return
    if baseline:
        print(f"[final_check] ALLOCATION CHANGED since the earlier run: {baseline['holding']} -> {final}")
    else:
        print(f"[final_check] no earlier run recorded for {today}; final-close allocation is {final}")
    notify.send_change_alert(preview, baseline, data_final)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[final_check] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
