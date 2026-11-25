"""Entry point for EventBridge Scheduler: {"kind": "morning" | "evening" | "late" | "weekly"}.

Times are configured in template.yaml (Europe/Kyiv).
"""

import logging
import os
from datetime import timedelta

import core
import repo
import telegram
import views

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    kind = (event or {}).get("kind")
    chat_id = int(os.environ["OWNER_CHAT_ID"])
    try:
        sent = run(kind, chat_id)
    except Exception:
        # Do not re-raise: an async retry would resend messages that already went out.
        logger.exception("Scheduler run failed: %s", kind)
        return {"ok": False, "kind": kind}
    logger.info("Scheduler %s: sent %d message(s)", kind, sent)
    return {"ok": True, "kind": kind, "sent": sent}


def run(kind, chat_id):
    """Send the reminder for `kind`. Returns how many messages were sent."""
    data = repo.load(chat_id)
    today = core.today_kyiv()
    days = data["days"]
    today_empty = not core.is_active(days.get(core.key(today)))

    if kind == "morning":
        telegram.send_message(chat_id, *views.morning_view(data, today))
        return 1

    if kind == "evening":
        sent = 0
        if today_empty:
            telegram.send_message(chat_id, *views.evening_empty_view(data, today))
            sent += 1
        repo.set_state(chat_id, awaiting_note_for=core.key(today))
        telegram.send_message(chat_id, views.NOTE_QUESTION)
        return sent + 1

    if kind == "late":
        if today_empty and core.missed(days, today - timedelta(days=1)):
            telegram.send_message(chat_id, *views.late_view(data, today))
            return 1
        return 0

    if kind == "weekly":
        telegram.send_message(chat_id, *views.weekly_report_view(data, today))
        return 1

    raise ValueError(f"Unknown kind: {kind!r}")
