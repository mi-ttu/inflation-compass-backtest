"""Waiting for Yahoo's final closing bars, shared by the after-close daily run
(run_daily.py) and the optional final-close check (run_final_check.py).

The daily run happens at 3:05 PM Central (4:05 PM ET), 5 minutes after the
close, so the email reports the definitive allocation from final closing
prices -- same schedule as the MaxAlpha backtest project. Yahoo's daily bars can
still move for a few minutes after 4 PM, so nothing counts as final before
FINAL_AFTER, and the bars must be identical on two consecutive polls. If that
doesn't happen within WAIT_MINUTES the run carries on with what it has and the
email says the closing prices may still move.

The 5-year breakeven isn't polled here: it comes from the Treasury/FRED
(ingest/fetch_fred.py), not from Yahoo.
"""
import time
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

import yfinance as yf

# The signal's market inputs -- keep in sync with live_preview.LIVE_TICKERS
# (not imported, because live_preview imports this module).
TICKERS = ("^GSPC", "XLE", "XLI", "XLF", "XLB", "XLU", "XLV", "XLP")
POLL_SECONDS = 60
WAIT_MINUTES = 15
ET = ZoneInfo("America/New_York")
MARKET_CLOSE = dtime(16, 0)
FINAL_AFTER = dtime(16, 5)


def after_close() -> bool:
    return datetime.now(ET).time() >= MARKET_CLOSE


def todays_bars() -> dict:
    """{ticker: (bar date, close)} for the latest daily bar of each input."""
    out = {}
    for t in TICKERS:
        h = yf.Ticker(t).history(period="5d", interval="1d", auto_adjust=False)
        out[t] = (h.index[-1].date(), round(float(h["Close"].iloc[-1]), 4))
    return out


def wait_for_final_close(today: date, log_prefix: str = "[close_data]") -> bool:
    """True once every input has a bar dated today that held steady across two
    consecutive polls after FINAL_AFTER; False if that doesn't happen within
    WAIT_MINUTES."""
    deadline = time.monotonic() + WAIT_MINUTES * 60
    previous = None
    while True:
        try:
            bars = todays_bars()
        except Exception as exc:
            print(f"{log_prefix} poll failed: {exc}", flush=True)
            bars = None
        if bars and all(d == today for d, _ in bars.values()) and datetime.now(ET).time() >= FINAL_AFTER:
            if previous is not None and bars == previous:
                print(f"{log_prefix} closing bars stable ({len(bars)} inputs, e.g. ^GSPC {bars['^GSPC'][1]})", flush=True)
                return True
            previous = bars
        else:
            previous = None
        if time.monotonic() + POLL_SECONDS > deadline:
            print(f"{log_prefix} closing bars did not stabilize in time -- proceeding with what's available", flush=True)
            return False
        time.sleep(POLL_SECONDS)
