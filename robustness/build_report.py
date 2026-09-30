"""Render robustness/results.json into robustness/report.html.

Styling (CSS, header, theme toggle) is shared with the MaxAlpha robustness
report: taken from ../max-alpha-backtest/robustness/report_template.html up to
its <script> tag. The findings text below was written for the run dated in
results.json; reread it after rerunning run_tests.py on new data.

Usage: .venv/Scripts/python.exe robustness/build_report.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent.parent / "max-alpha-backtest" / "robustness" / "report_template.html"

TEXT = {
    "overall": (
        "Inflation Compass passes these tests more convincingly than MaxAlpha. It did about as well before its published "
        "backtest period (24% a year over 1990–2002) as during it, choosing settings without hindsight lost only about 1 point "
        "a year, and its regime-to-holding assignment beats every alternative. Its signals add value whatever it holds in "
        "goldilocks. The one real weakness is trading: it flips between QLD and XLE often, so trading costs and the live "
        "2:30 PM decision cost it 3–4 points a year."
    ),
    "verdicts": [
        {"title": "Out of sample and signal value", "status": "good",
         "summary": "24.4%/yr over 1990–2002, before the published period (S&P 500: 7.3%). The published assignment of holdings to regimes ranks 1st of 24 in every period, and the signals beat buy-and-hold with QQQ, SPY or XLK too."},
        {"title": "Parameter robustness", "status": "good",
         "summary": "A broad plateau: 300 nearby settings span about 23–30%/yr. The published settings rank near the top over 2003–2026 but only mid-pack over 1990–2002, a mild sign of tuning to the published period."},
        {"title": "Execution stress", "status": "warn",
         "summary": "Late inflation data and a day's delay don't hurt. Trading costs do: about 11 trades a year, many 1–3 days long, so 10 bps per trade costs ~3 points a year and 25 bps ~7. The live 2:30 PM decision cost about 3.6 points a year recently."},
        {"title": "Walk-forward", "status": "good",
         "summary": "Choosing settings each year from past data only earned 28.8%/yr over 1993–2026, against 29.8% for the published settings."},
        {"title": "Synthetic histories", "status": "good",
         "summary": "Beat the S&P 500 in all 300 reshuffled histories and QLD's Sharpe ratio in 95% (median 26%/yr, bad case 16%). Drawdowns: median −49%, worse than −40% in 79% of histories."},
    ],
    "t1": (
        "Varadi's published backtest starts in 2003, so 1990–2002 is genuine out-of-sample data for the model. It earned 24.4% "
        "a year there, compared with 31.1% over the published period and 7.3% for the S&P 500. Even with a realistic "
        "financing cost on the 2× Nasdaq stand-in before QLD existed, it earned 22.9%. The signals also add value regardless "
        "of the goldilocks holding: with QQQ, SPY or XLK instead of QLD, each version beats buying and holding that fund on "
        "both return and Sharpe ratio. And of all 24 ways to assign the four holdings to the four regimes, the published one "
        "ranks first in 1990–2002, 2003–2026 and overall."
    ),
    "t1_note": (
        "Before 2003 the model uses stand-ins that the Inflation Compass project documents: the Cleveland Fed's 5-year "
        "expected-inflation estimate (monthly) instead of the T5YIE breakeven, Fama-French industry returns for the sector "
        "basket before the sector ETFs, and 2× the Nasdaq-100 for QLD before 2006. Since publication on July 27, 2026 there "
        "are only 46 trading days of live results, too few to judge."
    ),
    "t2": (
        "Results change gradually as each setting moves; there is no sharp peak. Across 300 random combinations the "
        "CAGR ranges from about 23% to 30% a year. The published settings rank at the 94th percentile over the published "
        "2003–2026 period but only the 38th over 1990–2002, which suggests some fitting to the period it was designed on. "
        "Even so, the typical nearby setting is only 2–4 points a year below the published one."
    ),
    "t2_note": (
        "The breakeven threshold is the most sensitive setting: 1.5–1.75% loses 5–6 points a year versus 2.0%. Lower "
        "thresholds switch into reflation (XLE) more often. Hover a dot for its drawdown."
    ),
    "t3": (
        "Timing is not a problem for Inflation Compass. Inflation data arriving one or two days late changes almost nothing, "
        "and even a full extra day of delay leaves CAGR unchanged. Trading costs are the issue. The strategy trades about "
        "11 times a year, and 44% of its holdings last three days or less, mostly flipping between QLD and XLE when the "
        "inflation signal sits near its boundary. At 10 basis points per trade CAGR falls about 3 points; at 25 about 7."
    ),
    "t3_note": (
        "The 2:30 PM check uses Yahoo 60-minute bars for the S&P 500 and the seven sector funds (3:30 PM ET) and inflation data "
        "one day late, as the live preview does. 12 of the 13 differing days were goldilocks/reflation flips, the same "
        "whipsaw. A minimum holding period, or requiring the inflation signal to hold for two days before switching, "
        "would likely recover most of this cost; that is a rule change to test separately, not part of the published model."
    ),
    "t4": (
        "Choosing settings each January using only past data, then trading them for the year, earned 28.8% a year over "
        "1993–2026 using all history so far, against 29.8% for the published settings. Using only the last three years "
        "earned 26.5%. Very little of the published result depends on hindsight about the settings."
    ),
    "t4_note": "Candidates are the published settings plus the 300 random nearby sets from test 2.",
    "t5": (
        "Shuffling 6-month blocks of the 2002–2026 history, with the S&P 500, inflation expectations, sector basket and "
        "funds kept moving together, creates 300 alternative histories. Inflation Compass beat the S&P 500 in all of them and "
        "had a better Sharpe ratio than just holding QLD in 95%. Its median worst drawdown was −49%, close to the backtest's "
        "own −46%."
    ),
    "t5_note": (
        "Shuffling keeps trends shorter than 6 months but breaks longer ones, and joins inflation-expectation levels from "
        "different periods at block edges, which can briefly flip the inflation signal."
    ),
    "method": (
        "All tests use one simulation engine built on the Inflation Compass project's own signal code, with every setting "
        "adjustable. With the published settings it reproduces the backtest's regimes on 100% of days and its daily returns "
        "exactly. None of these tests is fully out of sample for settings Varadi may have tuned on data before 2003; only live "
        "trading is."
    ),
}


def main():
    res = json.loads((HERE / "results.json").read_text())
    shell = SHELL.read_text(encoding="utf-8")
    head = shell[: shell.index("<script>")]
    head = head.replace("<title>MaxAlpha Robustness</title>", "<title>Inflation Compass Robustness</title>")
    head = head.replace("<h1>MaxAlpha Robustness</h1>", "<h1>Inflation Compass Robustness</h1>")
    head = head.replace("Five tests of whether MaxAlpha's backtested edge survives outside the exact data, settings and trading assumptions it was built on.",
                        "Five tests of whether the Inflation Compass Hybrid QLD/XLE daily strategy holds up outside the exact data, settings and trading assumptions it was built on.")
    head = head.replace("</style>", ".axis-small{fill:var(--muted-2);font-family:var(--font-mono);font-size:8.5px}\n</style>")
    theme = shell[shell.index("<script>"): shell.index("const R = __RESULTS_JSON__;")].replace("maxalpha_robust_theme", "ic_robust_theme")
    script = (HERE / "report_script.js").read_text(encoding="utf-8")
    html = head + theme + script.replace("__RESULTS_JSON__", json.dumps(res, separators=(",", ":"))).replace("__TEXT_JSON__", json.dumps(TEXT)) + "\n</script>\n"
    (HERE / "report.html").write_text(html, encoding="utf-8")
    print("wrote robustness/report.html")


if __name__ == "__main__":
    main()
