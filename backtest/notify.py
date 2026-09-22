"""Sends an email if and only if the Hybrid (QLD/XLE), Daily variant's
current holding has changed since the last run -- i.e. exactly when the
regime the strategy is in switches, not on every refresh.

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


def send_email(cfg: dict, subject: str, body: str) -> None:
    # Explicit utf-8 rather than letting MIMEText guess -- the body uses
    # an em dash and curly quotes, and this project has hit real mojibake
    # bugs before from relying on encoding auto-detection.
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["recipient_email"]

    with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30) as server:
        server.starttls()
        server.login(cfg["sender_email"], cfg["app_password"])
        server.send_message(msg)


def format_change_email(as_of: str, last: dict, current: dict) -> tuple[str, str]:
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

    subject, body = format_change_email(current_allocation["asOf"], last, daily)
    try:
        send_email(cfg, subject, body)
        old_label = HOLDING_LABELS.get(last.get("holding"), last.get("holding"))
        new_label = HOLDING_LABELS.get(daily["holding"], daily["holding"])
        print(f"[notify] sent allocation-change email: {old_label} -> {new_label}")
    except Exception as exc:
        print(f"[notify] FAILED to send email: {exc}")

    save_last_allocation(daily)
