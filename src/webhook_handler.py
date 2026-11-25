"""Entry point for the Lambda Function URL.

Routing by path: POST /webhook handles Telegram updates. /api/* is reserved
for the v2 Mini App API and returns 404 for now, as does any other path.
The real work (toggle, notes, day state) lives in repo.py / core.py so the
future API can reuse it.

Security:
- the request must carry X-Telegram-Bot-Api-Secret-Token == WEBHOOK_SECRET, else 403;
- only updates from OWNER_CHAT_ID are processed, everything else is silently ignored.

Telegram always gets 200 for authenticated requests, even on errors, so it
does not retry the same broken update forever.
"""

import base64
import hmac
import json
import logging
import os
import time
from datetime import timedelta
from html import escape

import core
import repo
import telegram
import views

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OK = {"statusCode": 200, "body": ""}
FORBIDDEN = {"statusCode": 403, "body": ""}
NOT_FOUND = {"statusCode": 404, "body": ""}


def lambda_handler(event, context):
    """Route by path: POST /webhook -> Telegram; /api/* is reserved for the v2 Mini App."""
    path = event.get("rawPath") or "/"
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "POST")
    if path == "/webhook" and method == "POST":
        return handle_webhook(event)
    return NOT_FOUND  # including /api/* until version 2


def handle_webhook(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    got = headers.get("x-telegram-bot-api-secret-token", "").encode()
    if not hmac.compare_digest(got, os.environ["WEBHOOK_SECRET"].encode()):
        return FORBIDDEN

    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body)
        update = json.loads(body)
    except (ValueError, TypeError):
        logger.warning("Bad request body")
        return OK

    owner = int(os.environ["OWNER_CHAT_ID"])
    try:
        handle_update(update, owner)
    except Exception:
        logger.exception("Failed to handle update %s", update.get("update_id"))
        if _sender_id(update) == owner:
            try:
                telegram.send_message(owner, views.ERROR)
            except Exception:
                logger.exception("Failed to send error message")
    return OK


def _sender_id(update):
    if "message" in update:
        return update["message"].get("chat", {}).get("id")
    if "callback_query" in update:
        return update["callback_query"].get("from", {}).get("id")
    return None


def handle_update(update, owner):
    if _sender_id(update) != owner:
        return  # not the owner: ignore silently
    if "callback_query" in update:
        handle_callback(update["callback_query"], owner)
    elif "message" in update:
        handle_message(update["message"], owner)


# ---------- buttons ----------

def handle_callback(cq, chat_id):
    try:
        prefix, day_key, kind, item_id = cq.get("data", "").split(":", 3)
        d = core.parse_date(day_key)
        if prefix != "x" or kind not in ("t", "h"):
            raise ValueError
    except ValueError:
        telegram.answer_callback(cq["id"])
        return

    data = repo.toggle_item(chat_id, core.key(d), kind, item_id)
    if data is None:
        telegram.answer_callback(cq["id"], "Цього пункту вже немає в плані")
        return

    today = core.today_kyiv()
    text, keyboard = views.day_view(data, d, today)
    message = cq.get("message")
    if message:
        telegram.edit_message(chat_id, message["message_id"], text, keyboard)
    telegram.answer_callback(cq["id"])


# ---------- messages ----------

def handle_message(message, chat_id):
    if "document" in message:
        handle_document(message, chat_id)
        return

    text = (message.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/"):
        command, _, args = text.partition(" ")
        command = command.split("@")[0].lower()
        handler = COMMANDS.get(command)
        if handler:
            handler(chat_id, args.strip())
        else:
            telegram.send_message(chat_id, views.UNKNOWN)
        return

    # Plain text: a note for the day the evening question was asked.
    if repo.save_pending_note(chat_id, text):
        telegram.send_message(chat_id, views.NOTE_SAVED)
    else:
        telegram.send_message(chat_id, views.UNKNOWN)


def cmd_start(chat_id, args):
    telegram.send_message(chat_id, *views.start_view())


def cmd_today(chat_id, args):
    today = core.today_kyiv()
    telegram.send_message(chat_id, *views.day_view(repo.load(chat_id), today, today))


def cmd_yesterday(chat_id, args):
    today = core.today_kyiv()
    telegram.send_message(chat_id, *views.day_view(repo.load(chat_id), today - timedelta(days=1), today))


def cmd_week(chat_id, args):
    telegram.send_message(chat_id, *views.week_view(repo.load(chat_id), core.today_kyiv()))


def cmd_streak(chat_id, args):
    telegram.send_message(chat_id, *views.streak_view(repo.load(chat_id), core.today_kyiv()))


def cmd_goals(chat_id, args):
    telegram.send_message(chat_id, *views.goals_view(repo.load(chat_id)))


def cmd_add(chat_id, args):
    date_arg, _, title = args.partition(" ")
    title = title.strip()
    d = core.parse_add_date(date_arg, core.today_kyiv()) if date_arg else None
    if not d or not title:
        telegram.send_message(
            chat_id,
            "Формат: /add &lt;дата&gt; &lt;назва&gt;\nДата: today, tomorrow або YYYY-MM-DD.\n"
            "Приклад: /add tomorrow Прочитати статтю",
        )
        return
    task = {
        "id": f"a{int(time.time() * 1000):x}",  # short, unique enough for one user
        "date": core.key(d),
        "title": title[:200],
        "area": core.DEFAULT_AREA,
        "goal": "",
        "xp": 0,
        "min": 0,
        "milestone": False,
    }
    repo.add_task(chat_id, task)
    telegram.send_message(chat_id, f"➕ Додав: {escape(task['title'])} — {core.fmt_day(d)}")


def cmd_import(chat_id, args):
    repo.set_state(chat_id, awaiting_import=True)
    telegram.send_message(chat_id, views.IMPORT_WAITING)


def cmd_export(chat_id, args):
    data = repo.load(chat_id)
    export = {k: data[k] for k in ("habits", "goals", "tasks", "minimums", "days")}
    content = json.dumps(export, ensure_ascii=False, indent=2).encode()
    filename = f"planabot-{core.key(core.today_kyiv())}.json"
    telegram.send_document(chat_id, filename, content, caption="Бекап PlanA 💾")


def handle_document(message, chat_id):
    data = repo.load(chat_id)
    caption = (message.get("caption") or "").strip().lower()
    if not data["state"].get("awaiting_import") and not caption.startswith("/import"):
        telegram.send_message(chat_id, "Щоб імпортувати план, спершу надішли /import.")
        return

    raw = telegram.get_file(message["document"]["file_id"])
    try:
        plan = core.validate_plan(json.loads(raw.decode("utf-8-sig")))
    except UnicodeDecodeError:
        telegram.send_message(chat_id, "❌ Файл має бути JSON у кодуванні UTF-8.")
        return
    except json.JSONDecodeError as e:
        telegram.send_message(chat_id, f"❌ Некоректний JSON: рядок {e.lineno}, позиція {e.colno}.")
        return
    except ValueError as e:
        telegram.send_message(chat_id, f"❌ {escape(str(e))}")
        return

    repo.replace_plan(chat_id, plan)
    repo.set_state(chat_id, awaiting_import=False)
    telegram.send_message(
        chat_id,
        f"✅ Імпортовано: звичок {len(plan['habits'])}, задач {len(plan['tasks'])}, "
        f"цілей {len(plan['goals'])}, мінімумів {len(plan['minimums'])}.\n/today — подивитися план",
    )


COMMANDS = {
    "/start": cmd_start,
    "/help": cmd_start,
    "/today": cmd_today,
    "/yesterday": cmd_yesterday,
    "/week": cmd_week,
    "/streak": cmd_streak,
    "/goals": cmd_goals,
    "/add": cmd_add,
    "/import": cmd_import,
    "/export": cmd_export,
}
