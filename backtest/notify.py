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


def send_email(cfg: dict, subject: str, text_body: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["recipient_email"]
    # Plain-text part first, HTML second -- per MIME convention the LAST
    # part is preferred, so a client that can render HTML shows that, and
    # anything that can't (or a user who reads raw source) still gets a
    # complete, readable plain-text version, not a pile of markup.
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
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


def format_daily_status_text(preview: dict) -> tuple[str, str]:
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
        f"CHANGE: the signal moves from {current['holding']} to {rec['holding']} (takes effect next session).\n\n"
        if changes else ""
    )
    body = (
        f"Hybrid (QLD/XLE), Daily variant.\n\n"
        f"Current allocation (held today, decided at the close of {current['date']}): {_describe(current)}\n\n"
        f"{rec_line}\n\n"
        f"{change_line}"
        f"Signal inputs: {_signal_inputs_text(rec)}\n\n"
        "Not investment advice — see the dashboard for the full picture."
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


def format_daily_status_html(preview: dict) -> str:
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
        rec_label = "Recommended at Today&rsquo;s Close &mdash; Live Preview"
        rec_sub = f"{REGIME_LABELS.get(rec['regime'], rec['regime'])} &mdash; live intraday preview, decided as-of now"
    else:
        rec_extra = ""
        rec_label = "Recommended at Today&rsquo;s Close &mdash; Final"
        rec_sub = f"{REGIME_LABELS.get(rec['regime'], rec['regime'])} &mdash; decided at the close of {rec['date']}"
    rec_extra += f"""
  <div style="{box}">
    <b>Signal inputs</b><br>{_signal_inputs_text(rec)}
  </div>"""
    rec_card = _card_html(rec_label, HOLDING_COLOR_HEX.get(rec["holding"], "#5b6272"), rec["holding"], rec_sub, rec_extra)

    change_banner = ""
    if changes:
        change_banner = f"""
  <div style="margin:0 24px;padding:10px 14px;background:#fff4e5;border:1px solid #f3c98b;border-radius:8px;font-size:13px;color:#7a4a00;font-family:{FONT_STACK};">
    <b>Change:</b> the signal moves from <b>{current['holding']}</b> to <b>{rec['holding']}</b> (takes effect next session).
  </div>"""

    return f"""
<div style="max-width:600px;margin:0 auto;font-family:{FONT_STACK};color:#171a24;background:#ffffff;">
  <div style="padding:22px 24px 16px;border-bottom:2px solid #eef0f6;">
    <div style="font-size:19px;font-weight:700;">Inflation Compass Daily Status</div>
    <div style="font-size:12.5px;color:#5b6272;margin-top:3px;">Hybrid (QLD/XLE), Daily &middot; latest session: <b>{rec['date']}</b></div>
  </div>{change_banner}
  <div style="padding:20px 24px 4px;">
    {current_card}
    {rec_card}
  </div>
  <div style="padding:6px 24px 22px;font-size:12px;color:#5b6272;line-height:1.6;font-family:{FONT_STACK};">
    <b>Not investment advice</b> &mdash; see the dashboard for the full picture.
  </div>
</div>"""


def send_daily_status(preview: dict) -> None:
    cfg = load_config()
    if cfg is None:
        print("[notify] email_config.json is missing/incomplete -- skipping daily status email")
        return

    subject, text_body = format_daily_status_text(preview)
    html_body = format_daily_status_html(preview)
    try:
        send_email(cfg, subject, text_body, html_body)
        print(f"[notify] sent daily status email: current={preview['current']['holding']} "
              f"recommended={preview['preview']['holding']} (live={preview['isLive']})")
    except Exception as exc:
        print(f"[notify] FAILED to send email: {exc}")
