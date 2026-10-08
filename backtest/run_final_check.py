"""3:15 PM Central final-close check: emails ONLY if the final close changed
the allocation the 2:30 PM run (run_daily.py) recommended.

3:15 PM Central is 4:15 PM Eastern, 15 minutes after the close. At 2:30 PM
the signal runs on live intraday quotes that can still move; this reruns it
on the day's real closing prices. If the recommended holding differs from the
one saved at 2:30 (see status_store.py) an alert goes out; if it's the same,
nothing is sent (the line goes to the log only). If no 2:30 baseline exists
for today (that run failed or never ran) the final allocation is sent anyway,
flagged as having no baseline.

Waiting for final data: Yahoo's daily bars can lag the close by several
minutes. Before the full refresh this polls ^GSPC and the seven sector ETFs
the signal uses once a minute until all are dated today and unchanged across
two consecutive polls, for up to WAIT_MINUTES. If that never happens the check
still runs on what it has, and the email says the data may not be final.

Usage: python.exe backtest/run_final_check.py
"""
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_preview
import notify
import refresh_chart
import run_daily
import status_store

TICKERS = tuple(live_preview.LIVE_TICKERS)
POLL_SECONDS = 60
WAIT_MINUTES = 15
ET = ZoneInfo("America/New_York")


def todays_bars() -> dict:
    """{ticker: (bar date, close)} for the latest daily bar of each input."""
    out = {}
    for t in TICKERS:
        h = yf.Ticker(t).history(period="5d", interval="1d", auto_adjust=False)
        out[t] = (h.index[-1].date(), round(float(h["Close"].iloc[-1]), 4))
    return out


def wait_for_final_close(today: date) -> bool:
    """True once every input has a bar dated today that held steady across two
    consecutive polls; False if that doesn't happen within WAIT_MINUTES."""
    deadline = time.monotonic() + WAIT_MINUTES * 60
    previous = None
    while True:
        try:
            bars = todays_bars()
        except Exception as exc:
            print(f"[final_check] poll failed: {exc}")
            bars = None
        if bars and all(d == today for d, _ in bars.values()):
            if bars == previous:
                print(f"[final_check] closing bars stable ({len(bars)} inputs)")
                return True
            previous = bars
        else:
            previous = None
        if time.monotonic() + POLL_SECONDS > deadline:
            print("[final_check] closing bars did not stabilize in time -- proceeding with what's available")
            return False
        time.sleep(POLL_SECONDS)


def main() -> None:
    today = date.today()
    if not run_daily.is_trading_day(today):
        print(f"[final_check] {today} is not an NYSE trading day -- nothing to do.")
        return
    if datetime.now(ET).hour < 16:
        print("[final_check] the market is still open (before 4 PM ET) -- the final close doesn't exist yet; exiting.")
        return

    data_final = wait_for_final_close(today)
    refresh_chart.main()
    preview = live_preview.build_preview()
    if preview["isLive"]:
        data_final = False  # today's bar still missing after the refresh: the preview fell back to live quotes
    baseline = status_store.load_baseline(today)
    final = preview["preview"]["holding"]

    if baseline and baseline["holding"] == final:
        print(f"[final_check] final close confirms the 2:30 PM allocation ({final}); no email sent.")
        return
    if baseline:
        print(f"[final_check] ALLOCATION CHANGED after 2:30 PM: {baseline['holding']} -> {final}")
    else:
        print(f"[final_check] no 2:30 PM baseline for {today}; final-close allocation is {final}")
    notify.send_change_alert(preview, baseline, data_final)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[final_check] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
