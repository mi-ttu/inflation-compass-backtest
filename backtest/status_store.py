"""The 2:30 PM run's decision, saved so the 3:15 PM final-close check
(run_final_check.py) can tell whether the final close changed it.

One small JSON file, overwritten each trading day. Local state only: it
lives under data/, which is git-ignored and never shipped in the release.
"""
import json
from datetime import date
from pathlib import Path

STATUS_PATH = Path(__file__).resolve().parent.parent / "data" / "last_status.json"


def snapshot(preview: dict, label: str) -> dict:
    """What the preview decided: the recommended holding, the two signal
    states, and the inputs/quotes it used."""
    rec = preview["preview"]
    return {
        "run": label,
        "isLive": bool(preview["isLive"]),
        "decisionDate": rec["date"],
        "holding": rec["holding"],
        "regime": rec["regime"],
        "growthUp": bool(rec["growthUp"]),
        "inflationOn": bool(rec["inflationOn"]),
        "inputs": rec["inputs"],
        "livePrices": preview["livePrices"],
    }


def save_baseline(preview: dict, label: str = "2:30 PM") -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps({"date": date.today().isoformat(), "baseline": snapshot(preview, label)}, indent=2),
        encoding="utf-8",
    )


def load_baseline(today: date) -> dict | None:
    """Today's saved 2:30 PM decision, or None (no file, unreadable, or a stale day)."""
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("date") != today.isoformat():
        return None
    return data.get("baseline")
