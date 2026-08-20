"""Build our own total-return index per ticker from raw close +
dividend events — not from yfinance's Adj Close directly.

daily_total_return[t] = (close[t] + dividend[t]) / close[t-1] - 1
total_return_index[t] = cumulative product of (1 + daily_total_return),
                         rebased to 1.0 on the ticker's first date.

Reconciles the result against vendor_adj_close (informational only —
vendor_adj_close is never used downstream) and flags tickers where the
two diverge more than a small tolerance, since Yahoo's adjustment
methodology has known quirks around special/return-of-capital
distributions.

Usage: .venv/Scripts/python.exe transform/build_total_return_index.py
"""
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"

RECONCILE_TOLERANCE = 0.02  # 2% cumulative drift tolerance vs vendor adj close


def build_for_ticker(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.DataFrame:
    prices = con.execute(
        "SELECT trading_date, close, vendor_adj_close FROM equity_prices WHERE ticker = ? ORDER BY trading_date",
        [ticker],
    ).df()
    divs = con.execute(
        "SELECT ex_date, amount FROM equity_dividends WHERE ticker = ?",
        [ticker],
    ).df()

    div_by_date = dict(zip(divs["ex_date"], divs["amount"])) if len(divs) else {}
    prices["dividend"] = prices["trading_date"].map(div_by_date).fillna(0.0)

    prev_close = prices["close"].shift(1)
    prices["daily_total_return"] = (prices["close"] + prices["dividend"]) / prev_close - 1.0
    prices.loc[0, "daily_total_return"] = 0.0  # first day: no prior close to compare to

    prices["total_return_index"] = (1.0 + prices["daily_total_return"]).cumprod()
    prices["ticker"] = ticker
    prices["is_forward_filled"] = False

    # Reconciliation check against vendor's own adjusted close, rebased the same way.
    vendor_rebased = prices["vendor_adj_close"] / prices["vendor_adj_close"].iloc[0]
    drift = (prices["total_return_index"] / vendor_rebased - 1.0).abs().max()
    status = "OK" if drift <= RECONCILE_TOLERANCE else "DIVERGENT"
    print(f"[total_return] {ticker}: {len(prices)} rows, max drift vs vendor adj close = {drift:.4f} [{status}]")

    return prices[["ticker", "trading_date", "total_return_index", "daily_total_return", "is_forward_filled"]]


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM equity_prices").fetchall()]

    con.execute("BEGIN TRANSACTION")
    try:
        for ticker in sorted(tickers):
            df = build_for_ticker(con, ticker)
            con.execute("DELETE FROM total_return_index WHERE ticker = ?", [ticker])
            con.execute(
                """
                INSERT INTO total_return_index
                    (ticker, trading_date, total_return_index, daily_total_return, is_forward_filled)
                SELECT ticker, trading_date, total_return_index, daily_total_return, is_forward_filled
                FROM df
                """
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    con.close()


if __name__ == "__main__":
    main()
