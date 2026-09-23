"""Sends an email if and only if the Hybrid (QLD/XLE), Daily variant's
current holding has changed since the last run -- i.e. exactly when the
regime the strategy is in switches, not on every refresh.

Sent as multipart/alternative: a plain-text version (the fallback used by
any client that can't render HTML) plus a rich-text HTML version, styled
the same way as the MaxAlpha backtest's daily status email (colored cards,
inline CSS, no external stylesheet since email clients don't reliably
support one) -- adapted here to a before/after change alert rather than a
daily status, since this project emails on regime change, not every day.
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


def load_last_allocation() -> dict | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_last_allocation(daily_info: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(daily_info), encoding="utf-8")


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


def format_change_email_text(as_of: str, last: dict, current: dict) -> tuple[str, str]:
    old_holding = HOLDING_LABELS.get(last.get("holding"), last.get("holding"))
    old_regime = REGIME_LABELS.get(last.get("regime"), last.get("regime"))
    new_holding = HOLDING_LABELS.get(current["holding"], current["holding"])
    new_regime = REGIME_LABELS.get(current["regime"], current["regime"])

    subject = f"Inflation Compass: daily allocation changed to {new_holding}"
    body = (
        f"The Hybrid (QLD/XLE), Daily variant's allocation changed as of {as_of}.\n\n"
        f"Previous: {old_holding} — {old_regime}\n"
        f"Now:      {new_holding} — {new_regime}\n\n"
        "Not investment advice — see the dashboard for the full picture."
    )
    return subject, body


def _card_html(label: str, color: str, holding: str, sub_html: str) -> str:
    holding_label = HOLDING_LABELS.get(holding, holding)
    return f"""
<div style="background:{color};border-radius:10px;padding:16px 18px;margin-bottom:14px;">
  <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:rgba(255,255,255,.85);font-family:{FONT_STACK};">{label}</div>
  <div style="font-size:23px;font-weight:700;color:#ffffff;margin-top:5px;font-family:{MONO_STACK};">{holding_label}</div>
  <div style="font-size:12.5px;color:rgba(255,255,255,.92);margin-top:5px;font-family:{FONT_STACK};">{sub_html}</div>
</div>"""


def format_change_email_html(as_of: str, last: dict, current: dict) -> str:
    old_color = HOLDING_COLOR_HEX.get(last.get("holding"), "#5b6272")
    new_color = HOLDING_COLOR_HEX.get(current["holding"], "#5b6272")

    old_card = _card_html(
        "Previous Allocation", old_color, last.get("holding"),
        REGIME_LABELS.get(last.get("regime"), last.get("regime")),
    )
    new_card = _card_html(
        "New Allocation", new_color, current["holding"],
        f"{REGIME_LABELS.get(current['regime'], current['regime'])} &mdash; as of {as_of}",
    )

    return f"""
<div style="max-width:600px;margin:0 auto;font-family:{FONT_STACK};color:#171a24;background:#ffffff;">
  <div style="padding:22px 24px 16px;border-bottom:2px solid #eef0f6;">
    <div style="font-size:19px;font-weight:700;">Inflation Compass Allocation Change</div>
    <div style="font-size:12.5px;color:#5b6272;margin-top:3px;">Hybrid (QLD/XLE), Daily &middot; as of <b>{as_of}</b></div>
  </div>
  <div style="padding:20px 24px 4px;">
    {old_card}
    {new_card}
  </div>
  <div style="padding:6px 24px 22px;font-size:12px;color:#5b6272;line-height:1.6;font-family:{FONT_STACK};">
    <b>Not investment advice</b> &mdash; see the dashboard for the full picture.
  </div>
</div>"""


def check_and_notify(current_allocation: dict) -> None:
    """current_allocation is refresh_chart.build_current_allocation()'s
    return value: {"asOf": ..., "monthly": {...}, "daily": {...}}."""
    daily = current_allocation["daily"]
    last = load_last_allocation()

    if last is None:
        # First run ever (or the state file was cleared) -- nothing to
        # compare against yet, so just record it rather than treating a
        # first observation as a "change".
        save_last_allocation(daily)
        return

    if last.get("holding") == daily.get("holding"):
        return  # unchanged -- no email, by design

    cfg = load_config()
    if cfg is None:
        print("[notify] allocation changed but email_config.json is missing/incomplete -- skipping notification")
        save_last_allocation(daily)
        return

    as_of = current_allocation["asOf"]
    subject, text_body = format_change_email_text(as_of, last, daily)
    html_body = format_change_email_html(as_of, last, daily)
    try:
        send_email(cfg, subject, text_body, html_body)
        old_label = HOLDING_LABELS.get(last.get("holding"), last.get("holding"))
        new_label = HOLDING_LABELS.get(daily["holding"], daily["holding"])
        print(f"[notify] sent allocation-change email: {old_label} -> {new_label}")
    except Exception as exc:
        print(f"[notify] FAILED to send email: {exc}")

    save_last_allocation(daily)
