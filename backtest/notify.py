"""Sends a daily status email -- unconditionally, every trading day this
runs -- reporting the Hybrid (QLD/XLE), Daily variant's current allocation
(held today, decided at the prior close) and the allocation the signal
recommends at the end of today's session (see live_preview.py: a live
intraday quote spliced in if today's session isn't over yet, or today's
real final close if it already is).

Sent as multipart/alternative: a plain-text version (the fallback used by
any client that can't render HTML) plus a rich-text HTML version, laid out
like the MaxAlpha backtest project's daily status email (a "Currently
Held" card and a "Recommended at Today's Close" card, colored cards,
inline CSS, no external stylesheet since email clients don't reliably
support one). HOLDING_COLOR_HEX below are deliberately more saturated than
the dashboard's own --regime-* pastel tokens: those are tuned for dark
text laid over them, these are tuned for white text on a solid card, so
they are NOT meant to be kept in sync hex-for-hex with the dashboard.

Reads SMTP credentials from a local, git-ignored email_config.json (see
email_config.example.json for the expected shape and how to get a Gmail
app password). If that file is missing or incomplete, sending is silently
skipped with a printed note -- a normal data refresh should never fail
just because email isn't configured, and this matters doubly for the
standalone-installed app, where most installs won't have set it up at all.

Not meant to be run standalone -- called from run_daily.py after a refresh.
"""
import json
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "backtest" / "email_config.json"

HOLDING_LABELS = {
    "XLE": "XLE (Energy)",
    "QLD": "QLD (2x Nasdaq-100)",
    "XLU": "XLU (Utilities)",
    "XLP+IEF_5050": "XLP + IEF (50/50)",
}
REGIME_LABELS = {
    "reflation": "Reflation",
    "goldilocks": "“Goldilocks”",
    "stagflation": "Stagflation",
    "disinflation": "Deflation / Disinflation",
}
HOLDING_COLOR_HEX = {
    "XLE": "#2f6fd6",
    "QLD": "#16a34a",
    "XLU": "#b91c1c",
    "XLP+IEF_5050": "#b45309",
}
FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO_STACK = "'SFMono-Regular',Consolas,'Liberation Mono',monospace"
REQUIRED_CONFIG_KEYS = ("smtp_host", "smtp_port", "sender_email", "app_password", "recipient_email")


def load_config() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not all(cfg.get(k) for k in REQUIRED_CONFIG_KEYS):
        return None
    return cfg


def send_email(cfg: dict, subject: str, text_body: str, html_body: str, images: list[tuple[str, bytes]] | None = None) -> None:
    """images: [(content_id, png_bytes)] embedded inline and referenced from
    the HTML as <img src="cid:content_id">."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["recipient_email"]
    # Plain-text part first, HTML second -- per MIME convention the LAST
    # part is preferred, so a client that can render HTML shows that, and
    # anything that can't (or a user who reads raw source) still gets a
    # complete, readable plain-text version, not a pile of markup.
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if images:
        # HTML + its inline images travel together as multipart/related.
        related = MIMEMultipart("related")
        related.attach(MIMEText(html_body, "html", "utf-8"))
        for cid, png in images:
            img = MIMEImage(png, "png")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=f"{cid.split('@')[0]}.png")
            related.attach(img)
        msg.attach(related)
    else:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30) as server:
        server.starttls()
        server.login(cfg["sender_email"], cfg["app_password"])
        server.send_message(msg)


def _describe(info: dict) -> str:
    holding = HOLDING_LABELS.get(info["holding"], info["holding"])
    return f"{holding} — {REGIME_LABELS.get(info['regime'], info['regime'])}"


def _signal_inputs_text(preview_info: dict) -> str:
    i = preview_info["inputs"]
    growth = "above" if preview_info["growthUp"] else "below"
    inflation = "ON" if preview_info["inflationOn"] else "OFF"
    return (
        f"S&P 500 {i['spx']:,.2f} is {growth} its 200-day average ({i['sma200']:,.2f}); "
        f"5y breakeven {i['breakeven']:.2f}% (target {i['breakevenTarget']:.1f}%, as of {i['inflationAsOf']}); "
        f"inflation signal {inflation}."
    )


def _pending_text(rec: dict) -> str:
    """One line about the 2-day confirmation rule, only when it is holding the
    allocation back from today's raw signal."""
    if not rec.get("pending"):
        return ""
    return (f"PENDING: today's raw signal reads {rec['rawHolding']}, but the 2-day confirmation rule keeps "
            f"{rec['holding']} until that regime shows on a second consecutive close. If the next close reads "
            f"{rec['rawHolding']} again, the allocation changes to {rec['rawHolding']}.")


RULE_NOTE = ("2-day confirmation rule: the allocation changes only after the same new regime shows on two "
             "consecutive closes, which filters out 1-2 day flips around a threshold.")


SHORT_LABELS = {"XLE": "XLE", "QLD": "QLD", "XLU": "XLU", "XLP+IEF_5050": "XLP+IEF"}
REGIME_SHORT = {**REGIME_LABELS, "disinflation": "Disinflation"}  # fits the matrix's narrow column on a phone


def _cid(chart: dict) -> str:
    return f"sig-{chart['key']}@inflationcompass"


def _build_charts(preview: dict) -> list[dict]:
    """The four input-signal charts, or [] if they can't be drawn (e.g.
    matplotlib isn't installed) -- an email without charts beats no email."""
    if preview.get("history") is None:
        return []
    try:
        import signal_charts
        return signal_charts.render_signal_charts(
            preview["history"], HOLDING_COLOR_HEX, preview["preview"]["inputs"]["inflationAsOf"])
    except Exception as exc:
        print(f"[notify] signal charts skipped: {exc}")
        return []


# Every combination of the four input signals, written compactly: None means
# "doesn't matter" (Level False makes Momentum/Sector irrelevant, and a True
# Momentum makes Sector irrelevant). Outcomes come from live_preview.decide(),
# the same function the daily signal uses, so this table can't drift from it.
MATRIX_PATTERNS = [
    # (growth, level, momentum, sector)
    (True, False, None, None),
    (True, True, True, None),
    (True, True, False, True),
    (True, True, False, False),
    (False, False, None, None),
    (False, True, True, None),
    (False, True, False, True),
    (False, True, False, False),
]


def _matrix_rows() -> list[dict]:
    from live_preview import decide
    rows = []
    for pat in MATRIX_PATTERNS:
        g, lv, m, s = pat
        d = decide(g, lv, bool(m), bool(s))
        rows.append({"pattern": pat, "inflationOn": d["inflationOn"], "holding": d["holding"], "regime": d["regime"]})
    return rows


def _current_states(history) -> tuple | None:
    if history is None or len(history) == 0:
        return None
    last = history.iloc[-1]
    return (bool(last["growth_up"]), bool(last["breakeven_above_target"]),
            bool(last["breakeven_momentum_up"]), bool(last["asset_momentum_up"]))


def _row_matches(pattern: tuple, states: tuple) -> bool:
    return all(p is None or p == s for p, s in zip(pattern, states))


def _matrix_text(history) -> list[str]:
    states = _current_states(history)
    if states is None:
        return []
    tf = lambda v: "-    " if v is None else ("True " if v else "False")  # noqa: E731
    out = ["", "Decision matrix -- four yes/no questions decide the allocation:",
           "  Growth:   is the S&P 500 above its 200-day average?",
           "  Level:    is the 5-year breakeven inflation rate above 2.0%?",
           "  Momentum: is that breakeven higher than it was 60 trading days ago?",
           "  Sector:   are cyclical sectors beating defensive ones over the last 60 days?",
           "  Inflation is ON only when Level is True and Momentum or Sector is True; Growth then picks",
           "  between the two allocations on each side. (- = that signal doesn't matter in the row)",
           "  The '<-- now' row is today's raw signal. " + RULE_NOTE,
           "",
           "  Growth | Level | Moment | Sector | Inflation | Allocation"]
    for r in _matrix_rows():
        g, lv, m, s = r["pattern"]
        mark = "   <-- now" if _row_matches(r["pattern"], states) else ""
        out.append(f"  {tf(g)}  | {tf(lv)} | {tf(m)}  | {tf(s)}  | {'ON ' if r['inflationOn'] else 'OFF'}       | "
                   f"{SHORT_LABELS.get(r['holding'], r['holding'])} ({REGIME_LABELS.get(r['regime'], r['regime'])}){mark}")
    return out


def _matrix_html(history) -> str:
    states = _current_states(history)
    if states is None:
        return ""
    th = (f"padding:6px 6px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;"
          f"color:#5b6272;text-align:center;border-bottom:2px solid #eef0f6;font-family:{FONT_STACK};")

    def tf(v) -> str:
        if v is None:
            return f'<span style="color:#9aa1b0;">&mdash;</span>'
        return f'<span style="color:{"#059669" if v else "#c0392b"};font-weight:700;">{"True" if v else "False"}</span>'

    body = ""
    for r in _matrix_rows():
        now = _row_matches(r["pattern"], states)
        bg = "background:#fff6d6;" if now else ""
        edge = "border-left:4px solid #f59e0b;" if now else "border-left:4px solid transparent;"
        td = f"padding:7px 6px;font-size:12px;text-align:center;border-bottom:1px solid #eef0f6;font-family:{MONO_STACK};{bg}"
        g, lv, m, s = r["pattern"]
        color = HOLDING_COLOR_HEX.get(r["holding"], "#5b6272")
        chip = (f'<span style="display:inline-block;background:{color};color:#ffffff;font-weight:700;padding:2px 8px;'
                f'border-radius:5px;font-size:11.5px;">{SHORT_LABELS.get(r["holding"], r["holding"])}</span> '
                f'<span style="font-family:{FONT_STACK};font-size:11px;color:#5b6272;">{REGIME_SHORT.get(r["regime"], r["regime"])}</span>')
        marker = ' <b style="color:#b45309;font-family:' + FONT_STACK + ';font-size:10.5px;">NOW</b>' if now else ""
        body += (f'<tr><td style="{td}{edge}">{tf(g)}</td><td style="{td}">{tf(lv)}</td><td style="{td}">{tf(m)}</td>'
                 f'<td style="{td}">{tf(s)}</td>'
                 f'<td style="{td}">{"<b>ON</b>" if r["inflationOn"] else "OFF"}</td>'
                 f'<td style="{td}text-align:left;">{chip}{marker}</td></tr>')
    return f"""
<div style="padding:4px 24px 8px;">
  <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#5b6272;font-family:{FONT_STACK};">Decision matrix</div>
  <div style="font-size:11.5px;color:#5b6272;margin:3px 0 8px;line-height:1.6;font-family:{FONT_STACK};">
    Four yes/no questions (charted below) decide the allocation:<br>
    <b>Growth</b> &mdash; is the S&amp;P 500 above its 200-day average?<br>
    <b>Level</b> &mdash; is the 5-year breakeven inflation rate above 2.0%?<br>
    <b>Momentum</b> &mdash; is that breakeven higher than it was 60 trading days ago?<br>
    <b>Sector</b> &mdash; are cyclical sectors beating defensive ones over the last 60 days?<br>
    Inflation is ON only when Level is True and Momentum or Sector is True. Growth then picks between the two
    allocations on each side. &mdash; means that signal doesn't matter in that row.<br>
    The <b>NOW</b> row is today's raw signal. {RULE_NOTE}
  </div>
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #dde1ea;border-radius:8px;border-collapse:separate;">
    <tr><th style="{th}">Growth</th><th style="{th}">Level</th><th style="{th}">Momentum</th><th style="{th}">Sector</th><th style="{th}">Inflation</th><th style="{th}text-align:left;">Allocation</th></tr>
    {body}
  </table>
</div>"""


def _signals_text(charts: list[dict] | None) -> list[str]:
    if not charts:
        return []
    return ["", "Signal status (inflation signal = level AND (momentum OR sector momentum)):"] + [
        f"  {c['title']}: {'True' if c['state'] else 'False'} ({c['text']})" for c in charts]


def _signals_html(charts: list[dict] | None, history) -> str:
    if not charts:
        return ""
    first, last = str(history["trading_date"].iloc[0])[:10], str(history["trading_date"].iloc[-1])[:10]
    legend = "".join(
        f'<span style="display:inline-block;margin-right:12px;white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:2px;background:{HOLDING_COLOR_HEX[k]};opacity:.55;vertical-align:middle;margin-right:4px;"></span>{SHORT_LABELS[k]}</span>'
        for k in ("XLE", "QLD", "XLU", "XLP+IEF_5050"))
    blocks = ""
    for c in charts:
        badge_bg, badge_label = ("#059669", "True") if c["state"] else ("#c0392b", "False")
        blocks += f"""
    <div style="border:1px solid #dde1ea;border-radius:10px;padding:12px 14px 8px;margin-bottom:12px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="font-size:13.5px;font-weight:700;color:#171a24;font-family:{FONT_STACK};">{c["title"]}</td>
        <td align="right" style="white-space:nowrap;"><span style="display:inline-block;background:{badge_bg};color:#ffffff;font-size:11.5px;font-weight:700;padding:2px 10px;border-radius:5px;font-family:{FONT_STACK};">{badge_label}</span></td>
      </tr></table>
      <div style="font-size:11.5px;color:#5b6272;margin:3px 0 8px;font-family:{MONO_STACK};">{c["text"]}</div>
      <img src="cid:{_cid(c)}" alt="{c["title"]} chart" width="552" style="display:block;width:100%;max-width:552px;height:auto;border:0;">
    </div>"""
    return f"""
<div style="padding:4px 24px 4px;">
  <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#5b6272;font-family:{FONT_STACK};">Signal status</div>
  <div style="font-size:11.5px;color:#5b6272;margin:3px 0 12px;line-height:1.55;font-family:{FONT_STACK};">
    {first} to {last}. Black line = the input; magenta = its threshold or reference. Inflation signal = level AND
    (momentum OR sector momentum); growth and inflation together pick the regime. Background = holding decided that day: {legend}
  </div>{blocks}
</div>"""


def format_daily_status_text(preview: dict, charts: list[dict] | None = None) -> tuple[str, str]:
    """preview is live_preview.build_preview()'s return value:
    {"current": {...}, "preview": {...}, "isLive": bool, "livePrices": dict|None}."""
    current, rec = preview["current"], preview["preview"]
    changes = current["holding"] != rec["holding"]

    subject = f"Inflation Compass daily status: holding {current['holding']}, recommended {rec['holding']}"
    if changes:
        subject += " (CHANGE)"

    if preview["isLive"]:
        quotes = ", ".join(f"{k}={v:,.2f}" for k, v in preview["livePrices"].items())
        rec_line = (
            f"Recommended allocation at today's close (live preview, decided as-of now): {_describe(rec)}\n"
            f"  This is NOT final -- it can still change before today's ({rec['date']}) close.\n"
            f"  Quote inputs: {quotes}"
        )
    else:
        rec_line = f"Recommended allocation at today's close (already final): {_describe(rec)}"

    change_line = (
        f"CHANGE: the signal moves from {current['holding']} to {rec['holding']} (takes effect next session). "
        f"The new regime has now shown on two consecutive closes.\n\n"
        if changes else ""
    ) + (_pending_text(rec) + "\n\n" if rec.get("pending") else "")
    body = (
        f"Hybrid (QLD/XLE), Daily variant with 2-day regime confirmation.\n\n"
        f"Current allocation (held today, decided at the close of {current['date']}): {_describe(current)}\n\n"
        f"{rec_line}\n\n"
        f"{change_line}"
        f"Signal inputs: {_signal_inputs_text(rec)}\n"
        + "\n".join(_matrix_text(preview.get("history")) + _signals_text(charts))
        + "\n\nNot investment advice — see the dashboard for the full picture."
    )
    return subject, body


def _card_html(label: str, color: str, holding: str, sub_html: str, extra_html: str = "") -> str:
    holding_label = HOLDING_LABELS.get(holding, holding)
    return f"""
<div style="background:{color};border-radius:10px;padding:16px 18px;margin-bottom:14px;">
  <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:rgba(255,255,255,.85);font-family:{FONT_STACK};">{label}</div>
  <div style="font-size:23px;font-weight:700;color:#ffffff;margin-top:5px;font-family:{MONO_STACK};">{holding_label}</div>
  <div style="font-size:12.5px;color:rgba(255,255,255,.92);margin-top:5px;font-family:{FONT_STACK};">{sub_html}</div>
  {extra_html}
</div>"""


def format_daily_status_html(preview: dict, charts: list[dict] | None = None) -> str:
    current, rec = preview["current"], preview["preview"]
    changes = current["holding"] != rec["holding"]

    current_card = _card_html(
        "Currently Held",
        HOLDING_COLOR_HEX.get(current["holding"], "#5b6272"),
        current["holding"],
        f"{REGIME_LABELS.get(current['regime'], current['regime'])} &mdash; decided at the close of {current['date']}",
    )

    box = "margin-top:10px;padding:9px 11px;background:rgba(255,255,255,.16);border-radius:6px;font-size:11.5px;color:#ffffff;font-family:{f};line-height:1.5;".format(f=FONT_STACK)
    if preview["isLive"]:
        quotes = ", ".join(f"{k}={v:,.2f}" for k, v in preview["livePrices"].items())
        rec_extra = f"""
  <div style="{box}">
    <b>Not final</b> &mdash; can still change before today's {rec['date']} close.<br>
    Quote inputs: <span style="font-family:{MONO_STACK};">{quotes}</span>
  </div>"""
        rec_label = "Recommended at Today&rsquo;s Close &mdash; Live Preview &middot; 2-day rule"
        rec_sub = f"{REGIME_LABELS.get(rec['regime'], rec['regime'])} &mdash; live intraday preview, decided as-of now"
    else:
        rec_extra = ""
        rec_label = "Recommended at Today&rsquo;s Close &mdash; Final &middot; 2-day rule"
        rec_sub = f"{REGIME_LABELS.get(rec['regime'], rec['regime'])} &mdash; decided at the close of {rec['date']}"
    if rec.get("pending"):
        rec_extra += f"""
  <div style="{box}">
    <b>Pending confirmation</b> &mdash; today's raw signal reads <b>{rec['rawHolding']}</b>, but the 2-day rule keeps
    <b>{rec['holding']}</b> until that regime shows on a second consecutive close. If the next close reads
    {rec['rawHolding']} again, the allocation changes to {rec['rawHolding']}.
  </div>"""
    rec_extra += f"""
  <div style="{box}">
    <b>Signal inputs</b><br>{_signal_inputs_text(rec)}
  </div>"""
    rec_card = _card_html(rec_label, HOLDING_COLOR_HEX.get(rec["holding"], "#5b6272"), rec["holding"], rec_sub, rec_extra)

    change_banner = ""
    if changes:
        change_banner = f"""
  <div style="margin:0 24px;padding:10px 14px;background:#fff4e5;border:1px solid #f3c98b;border-radius:8px;font-size:13px;color:#7a4a00;font-family:{FONT_STACK};">
    <b>Change:</b> the signal moves from <b>{current['holding']}</b> to <b>{rec['holding']}</b> (takes effect next session); the new regime has now shown on two consecutive closes.
  </div>"""

    return f"""
<div style="max-width:600px;margin:0 auto;font-family:{FONT_STACK};color:#171a24;background:#ffffff;">
  <div style="padding:22px 24px 16px;border-bottom:2px solid #eef0f6;">
    <div style="font-size:19px;font-weight:700;">Inflation Compass Daily Status</div>
    <div style="font-size:12.5px;color:#5b6272;margin-top:3px;">Hybrid (QLD/XLE), Daily with 2-day confirmation &middot; latest session: <b>{rec['date']}</b></div>
  </div>{change_banner}
  <div style="padding:20px 24px 4px;">
    {current_card}
    {rec_card}
  </div>
  {_matrix_html(preview.get("history"))}
  {_signals_html(charts, preview.get("history"))}
  <div style="padding:6px 24px 22px;font-size:12px;color:#5b6272;line-height:1.6;font-family:{FONT_STACK};">
    <b>Not investment advice</b> &mdash; see the dashboard for the full picture.
  </div>
</div>"""


def send_daily_status(preview: dict) -> None:
    cfg = load_config()
    if cfg is None:
        print("[notify] email_config.json is missing/incomplete -- skipping daily status email")
        return

    charts = _build_charts(preview)
    subject, text_body = format_daily_status_text(preview, charts)
    html_body = format_daily_status_html(preview, charts)
    try:
        send_email(cfg, subject, text_body, html_body, [(_cid(c), c["png"]) for c in charts])
        print(f"[notify] sent daily status email: current={preview['current']['holding']} "
              f"recommended={preview['preview']['holding']} (live={preview['isLive']}, {len(charts)} signal charts)")
    except Exception as exc:
        print(f"[notify] FAILED to send email: {exc}")


# ---- 3:15 PM final-close check (run_final_check.py) ----
def _final_details(preview: dict, baseline: dict | None) -> dict:
    """What moved between the 2:30 PM snapshot and the final close."""
    final = preview["preview"]
    flipped, moves = [], []
    if baseline:
        if baseline["growthUp"] != final["growthUp"]:
            flipped.append(f"Growth (S&P 500 vs 200-day average): {'up' if baseline['growthUp'] else 'down'} -> {'up' if final['growthUp'] else 'down'}")
        if baseline["inflationOn"] != final["inflationOn"]:
            flipped.append(f"Inflation signal: {'ON' if baseline['inflationOn'] else 'OFF'} -> {'ON' if final['inflationOn'] else 'OFF'}")
        old_spx, new_spx = baseline["inputs"]["spx"], final["inputs"]["spx"]
        moves.append(f"S&P 500 {old_spx:,.2f} -> {new_spx:,.2f} ({new_spx / old_spx - 1:+.2%}); "
                     f"200-day average {final['inputs']['sma200']:,.2f}")
    return {"flipped": flipped, "moves": moves}


def format_change_alert(preview: dict, baseline: dict | None, data_final: bool,
                        charts: list[dict] | None = None) -> tuple[str, str, str]:
    final = preview["preview"]
    new = final["holding"]
    d = _final_details(preview, baseline)
    if baseline:
        old = baseline["holding"]
        subject = f"Inflation Compass ALERT: allocation changed after the 2:30 PM run: {old} -> {new}"
        headline = f"The final close changed the recommended allocation from {old} (2:30 PM preview) to {new}."
    else:
        old = None
        subject = f"Inflation Compass final close: recommended allocation {new} (no 2:30 PM baseline today)"
        headline = f"No 2:30 PM run was recorded today to compare against; the final-close allocation is {new}."
    warn = "" if data_final else (
        "Warning: Yahoo's daily bars for today had not stabilized when this ran, so these closing prices may still move.")

    text = [headline, ""]
    if old:
        text.append(f"2:30 PM preview: {_describe(baseline)}")
    text.append(f"Final close ({final['date']}): {_describe(final)}")
    if d["flipped"]:
        text += ["", "Signals that flipped since 2:30 PM:"] + [f"  {x}" for x in d["flipped"]]
    if d["moves"]:
        text += ["", "Closing prices vs the 2:30 PM snapshot:"] + [f"  {x}" for x in d["moves"]]
    if final.get("pending"):
        text += ["", _pending_text(final)]
    text += ["", f"Signal inputs: {_signal_inputs_text(final)}"] + _matrix_text(preview.get("history")) + _signals_text(charts)
    if warn:
        text += ["", warn]
    text += ["", "Not investment advice — see the dashboard for the full picture."]

    cards = ""
    if old:
        cards += _card_html("2:30 PM preview", HOLDING_COLOR_HEX.get(old, "#5b6272"), old,
                            f"{REGIME_LABELS.get(baseline['regime'], baseline['regime'])} &mdash; live intraday snapshot")
    cards += _card_html("Final close signal" + (" &mdash; CHANGED" if old else ""),
                        HOLDING_COLOR_HEX.get(new, "#5b6272"), new,
                        f"{REGIME_LABELS.get(final['regime'], final['regime'])} &mdash; decided at the close of {final['date']}")
    li = lambda items: "".join(f"<li>{x}</li>" for x in items)  # noqa: E731
    ul = f"margin:0 0 8px 18px;padding:0;font-family:{MONO_STACK};font-size:12px;"
    head = "font-size:12.5px;font-weight:700;margin:6px 0 2px;"
    detail = ""
    if d["flipped"]:
        detail += f'<div style="{head}">Signals that flipped since 2:30 PM</div><ul style="{ul}">{li(d["flipped"])}</ul>'
    if d["moves"]:
        detail += f'<div style="{head}">Closing prices vs the 2:30 PM snapshot</div><ul style="{ul}">{li(d["moves"])}</ul>'
    detail += f'<div style="font-size:12px;color:#5b6272;margin:6px 0;">{_signal_inputs_text(final)}</div>'
    warn_html = (f'<div style="margin:8px 0;padding:9px 11px;background:#fff4e5;border:1px solid #f0c27b;'
                 f'border-radius:6px;font-size:12px;color:#7a4a00;">{warn}</div>') if warn else ""
    title = "Allocation Changed" if old else "Final-Close Signal"
    html = f"""
<div style="max-width:600px;margin:0 auto;font-family:{FONT_STACK};color:#171a24;background:#ffffff;">
  <div style="padding:22px 24px 16px;border-bottom:2px solid #eef0f6;">
    <div style="font-size:19px;font-weight:700;">Inflation Compass &mdash; {title}</div>
    <div style="font-size:12.5px;color:#5b6272;margin-top:3px;">{headline}</div>
  </div>
  <div style="padding:20px 24px 4px;">
    {cards}
    <div style="font-size:12.5px;color:#171a24;line-height:1.55;font-family:{FONT_STACK};">{detail}{warn_html}</div>
  </div>
  {_matrix_html(preview.get("history"))}
  {_signals_html(charts, preview.get("history"))}
  <div style="padding:6px 24px 22px;font-size:12px;color:#5b6272;line-height:1.6;font-family:{FONT_STACK};">
    <b>Not investment advice</b> &mdash; see the dashboard for the full picture.
  </div>
</div>"""
    return subject, "\n".join(text), html


def send_change_alert(preview: dict, baseline: dict | None, data_final: bool) -> bool:
    cfg = load_config()
    if cfg is None:
        print("[notify] email_config.json is missing/incomplete -- skipping the final-close email")
        return False
    charts = _build_charts(preview)
    subject, text_body, html_body = format_change_alert(preview, baseline, data_final, charts)
    try:
        send_email(cfg, subject, text_body, html_body, [(_cid(c), c["png"]) for c in charts])
        print(f"[notify] sent final-close email: {subject}")
        return True
    except Exception as exc:
        print(f"[notify] FAILED to send final-close email: {exc}")
        return False
