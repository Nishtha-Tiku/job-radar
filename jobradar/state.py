import datetime as dt
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "sent.json"


def load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(sent: dict, today: dt.date, keep_days: int = 60) -> None:
    cutoff = (today - dt.timedelta(days=keep_days)).isoformat()
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    PATH.write_text(json.dumps(sent, indent=1, sort_keys=True))
