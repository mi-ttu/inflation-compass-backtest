"""Sends a daily status email -- unconditionally, every trading day this
runs -- reporting the Hybrid (QLD/XLE), Daily variant's current holding,
how long it's been held, and (when today's refresh actually changed it)
what it switched from.

Sent as multipart/alternative: a plain-text version (the fallback used by
any client that can't render HTML) plus a rich-text HTML version, styled
the same way as the MaxAlpha backtest project's daily status email
(colored cards, inline CSS, no external stylesheet since email clients
don't reliably support one). Adapted from MaxAlpha's own "Currently Held /
Next Session's Signal" two-card layout: this project doesn't have a live
intraday-preview subsystem, so there's no "next signal" to show -- instead
the single Current Allocation card shows how long the position has been
held, and a second card only appears on the day it actually changes.
HOLDING_COLOR_HEX below are deliberately more saturated than the
dashboard's own --regime-* pastel tokens: those are tuned for dark text
laid over them, these are tuned for white text on a solid card, so they
are NOT meant to be kept in sync hex-for-hex with the dashboard.

Reads SMTP credentials from a local, git-ignored email_config.json (see
email_config.example.json for the expected shape and how to get a Gmail
app password). If that file is missing or incomplete, notification is
silently skipped with a printed note -- a normal data refresh should never
fail just because email isn't configured, and this matters doubly for the
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
STATE_PATH = PROJECT_ROOT / "data" / "last_allocation.json"

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


def load_last_sent() -> dict | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_last_sent(daily_info: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"holding": daily_info["holding"], "regime": daily_info["regime"]}), encoding="utf-8")


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


def _describe(holding: str, regime: str) -> str:
    return f"{HOLDING_LABELS.get(holding, holding)} — {REGIME_LABELS.get(regime, regime)}"


def format_status_email_text(as_of: str, daily: dict, changed_from: dict | None) -> tuple[str, str]:
    holding_label = HOLDING_LABELS.get(daily["holding"], daily["holding"])
    subject = f"Inflation Compass daily status: holding {holding_label}"

    if changed_from is not None:
        subject = f"Inflation Compass: allocation changed to {holding_label}"
        change_line = (
            f"This changed today -- previous holding was {_describe(changed_from['holding'], changed_from['regime'])}.\n\n"
        )
    else:
        change_line = ""

    body = (
        f"Hybrid (QLD/XLE), Daily variant -- current status as of {as_of}.\n\n"
        f"Currently holding: {_describe(daily['holding'], daily['regime'])}\n"
        f"Held since: {daily['since']}\n\n"
        f"{change_line}"
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


def format_status_email_html(as_of: str, daily: dict, changed_from: dict | None) -> str:
    color = HOLDING_COLOR_HEX.get(daily["holding"], "#5b6272")
    current_card = _card_html(
        "Current Allocation", color, daily["holding"],
        f"{REGIME_LABELS.get(daily['regime'], daily['regime'])} &mdash; held since <b>{daily['since']}</b>",
    )

    if changed_from is not None:
        prev_color = HOLDING_COLOR_HEX.get(changed_from["holding"], "#5b6272")
        prev_card = _card_html(
            "Previous Allocation (until today)", prev_color, changed_from["holding"],
            REGIME_LABELS.get(changed_from["regime"], changed_from["regime"]),
        )
        cards = prev_card + current_card
        title = "Inflation Compass — Allocation Changed"
    else:
        cards = current_card
        title = "Inflation Compass Daily Status"

    return f"""
<div style="max-width:600px;margin:0 auto;font-family:{FONT_STACK};color:#171a24;background:#ffffff;">
  <div style="padding:22px 24px 16px;border-bottom:2px solid #eef0f6;">
    <div style="font-size:19px;font-weight:700;">{title}</div>
    <div style="font-size:12.5px;color:#5b6272;margin-top:3px;">Hybrid (QLD/XLE), Daily &middot; as of <b>{as_of}</b></div>
  </div>
  <div style="padding:20px 24px 4px;">
    {cards}
  </div>
  <div style="padding:6px 24px 22px;font-size:12px;color:#5b6272;line-height:1.6;font-family:{FONT_STACK};">
    <b>Not investment advice</b> &mdash; see the dashboard for the full picture.
  </div>
</div>"""


def check_and_notify(current_allocation: dict) -> None:
    """current_allocation is refresh_chart.build_current_allocation()'s
    return value: {"asOf": ..., "monthly": {...}, "daily": {...}}. Sends a
    status email every time this is called (i.e. every trading day the
    scheduled task runs) -- not just on a regime change."""
    daily = current_allocation["daily"]
    as_of = current_allocation["asOf"]
    last_sent = load_last_sent()
    changed_from = last_sent if (last_sent is not None and last_sent.get("holding") != daily.get("holding")) else None

    cfg = load_config()
    if cfg is None:
        print("[notify] email_config.json is missing/incomplete -- skipping daily status email")
        save_last_sent(daily)
        return

    subject, text_body = format_status_email_text(as_of, daily, changed_from)
    html_body = format_status_email_html(as_of, daily, changed_from)
    try:
        send_email(cfg, subject, text_body, html_body)
        tag = "changed" if changed_from is not None else "unchanged"
        print(f"[notify] sent daily status email ({tag}): {daily['holding']}")
    except Exception as exc:
        print(f"[notify] FAILED to send email: {exc}")

    save_last_sent(daily)
