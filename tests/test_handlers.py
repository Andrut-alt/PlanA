"""Handler tests with in-memory fakes for repo and telegram (no AWS, no network)."""

import copy
import json
import sys
import types
from datetime import date

import pytest

# boto3 is only available inside Lambda; repo.py imports it at module level.
sys.modules.setdefault("boto3", types.ModuleType("boto3"))

import core  # noqa: E402
import repo  # noqa: E402
import scheduler_handler  # noqa: E402
import telegram  # noqa: E402
import views  # noqa: E402
import webhook_handler  # noqa: E402

OWNER = 111
SECRET = "s" * 40
TODAY = date(2026, 11, 26)

PLAN = {
    "habits": [{"id": "h1", "title": "Зарядка"}],
    "goals": [{"id": "g1", "title": "Ціль", "horizon": "Грудень"}],
    "tasks": [
        {"id": "t1", "date": "2026-11-24", "title": "Стара <задача>", "goal": "g1"},
        {"id": "t2", "date": "2026-11-26", "title": "Сьогоднішня", "goal": "g1"},
    ],
    "minimums": {"2026-11-26": "20 хв"},
    "rewards": [{"id": "r1", "title": "Кіно", "cost": 40}],  # v2 field, ignored in v1
}


class FakeRepo:
    def __init__(self):
        self.data = {"habits": [], "tasks": [], "goals": [], "minimums": {}, "days": {}, "state": {}}

    def load(self, chat_id):
        return copy.deepcopy(self.data)

    def _day(self, k):
        return self.data["days"].setdefault(k, {"done": [], "note": None})

    def save_day_done(self, chat_id, k, done):
        self._day(k)["done"] = list(done)

    def save_note(self, chat_id, k, note):
        self._day(k)["note"] = note

    def set_state(self, chat_id, **fields):
        self.data["state"].update(fields)

    def add_task(self, chat_id, task):
        self.data["tasks"].append(task)

    def replace_plan(self, chat_id, plan):
        for k in ("habits", "tasks", "goals", "minimums"):
            self.data[k] = copy.deepcopy(plan[k])


class FakeTelegram:
    def __init__(self):
        self.sent, self.edited, self.answered, self.documents = [], [], [], []
        self.files = {}

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        self.edited.append((message_id, text, reply_markup))

    def answer_callback(self, cq_id, text=None):
        self.answered.append(cq_id)

    def send_document(self, chat_id, filename, content, caption=None):
        self.documents.append((filename, content))

    def get_file(self, file_id):
        return self.files[file_id]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OWNER_CHAT_ID", str(OWNER))
    fr, ft = FakeRepo(), FakeTelegram()
    for name in ("load", "save_day_done", "save_note", "set_state", "add_task", "replace_plan"):
        monkeypatch.setattr(repo, name, getattr(fr, name))
    for name in ("send_message", "edit_message", "answer_callback", "send_document", "get_file"):
        monkeypatch.setattr(telegram, name, getattr(ft, name))
    monkeypatch.setattr(core, "today_kyiv", lambda now=None: TODAY)
    return fr, ft


def call(update, secret=SECRET):
    return webhook_handler.lambda_handler(http_event("/webhook", secret=secret, body=json.dumps(update)), None)


def http_event(path, method="POST", secret=SECRET, body=""):
    """Minimal Lambda Function URL event (payload format 2.0)."""
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"X-Telegram-Bot-Api-Secret-Token": secret},
        "body": body,
        "isBase64Encoded": False,
    }


def msg(text=None, chat=OWNER, **extra):
    m = {"message_id": 1, "chat": {"id": chat}, "from": {"id": chat}, **extra}
    if text is not None:
        m["text"] = text
    return {"update_id": 1, "message": m}


def tap(data, chat=OWNER):
    return {"update_id": 2, "callback_query": {
        "id": "cb", "from": {"id": chat}, "data": data, "message": {"message_id": 77, "chat": {"id": chat}},
    }}


def do_import(fr, ft):
    ft.files["f1"] = json.dumps(PLAN, ensure_ascii=False).encode()
    call(msg("/import"))
    call(msg(document={"file_id": "f1", "file_name": "plan.json"}))


# ---------- security ----------

def test_wrong_secret_is_403(env):
    fr, ft = env
    assert call(msg("/start"), secret="wrong")["statusCode"] == 403
    assert call(msg("/start"), secret="")["statusCode"] == 403
    assert ft.sent == []


def test_stranger_is_ignored(env):
    fr, ft = env
    assert call(msg("/start", chat=999))["statusCode"] == 200
    assert call(tap("x:2026-11-26:h:h1", chat=999))["statusCode"] == 200
    assert ft.sent == [] and ft.answered == []


def test_error_returns_200_and_apology(env, monkeypatch):
    fr, ft = env
    monkeypatch.setattr(repo, "load", lambda chat_id: 1 / 0)
    assert call(msg("/today"))["statusCode"] == 200
    assert ft.sent[-1][1] == views.ERROR


def test_bad_body_is_200(env):
    assert webhook_handler.lambda_handler(http_event("/webhook", body="not json"), None)["statusCode"] == 200


# ---------- routing ----------

@pytest.mark.parametrize("path,method", [
    ("/api/state", "GET"),
    ("/api/toggle", "POST"),
    ("/", "POST"),
    ("/webhook", "GET"),
    ("/webhook/", "POST"),
])
def test_other_routes_are_404(env, path, method):
    fr, ft = env
    body = json.dumps(msg("/start"))
    assert webhook_handler.lambda_handler(http_event(path, method, body=body), None)["statusCode"] == 404
    assert ft.sent == []


def test_base64_body(env):
    import base64
    fr, ft = env
    event = http_event("/webhook", body=base64.b64encode(json.dumps(msg("/start")).encode()).decode())
    event["isBase64Encoded"] = True
    assert webhook_handler.lambda_handler(event, None)["statusCode"] == 200
    assert "/today" in ft.sent[-1][1]


# ---------- commands ----------

def test_start(env):
    fr, ft = env
    call(msg("/start"))
    assert "/today" in ft.sent[-1][1]


def test_import_today_and_toggle(env):
    fr, ft = env
    do_import(fr, ft)
    assert "Імпортовано" in ft.sent[-1][1]
    assert fr.data["state"]["awaiting_import"] is False

    call(msg("/today"))
    text, kb = ft.sent[-1][1], ft.sent[-1][2]
    assert "20 хв" in text
    labels = [r[0]["text"] for r in kb["inline_keyboard"]]
    assert labels[0].startswith("⬜ Стара <задача> · ⏳ з Вт 24.11")

    call(tap("x:2026-11-26:t:t1"))
    assert fr.data["days"]["2026-11-26"]["done"] == ["t:t1"]
    assert ft.edited[-1][0] == 77 and ft.answered[-1] == "cb"
    assert ft.edited[-1][2]["inline_keyboard"][0][0]["text"].startswith("✅")

    call(tap("x:2026-11-26:t:t1"))
    assert fr.data["days"]["2026-11-26"]["done"] == []


def test_import_keeps_history(env):
    fr, ft = env
    fr.data["days"]["2026-11-23"] = {"done": ["h:old"], "note": "n"}
    do_import(fr, ft)
    assert fr.data["days"]["2026-11-23"] == {"done": ["h:old"], "note": "n"}


def test_import_invalid_json(env):
    fr, ft = env
    ft.files["bad"] = b"{oops"
    call(msg("/import"))
    call(msg(document={"file_id": "bad"}))
    assert "Некоректний JSON" in ft.sent[-1][1]
    assert fr.data["tasks"] == []


def test_document_without_import_is_rejected(env):
    fr, ft = env
    ft.files["f1"] = json.dumps(PLAN).encode()
    call(msg(document={"file_id": "f1"}))
    assert "/import" in ft.sent[-1][1]
    assert fr.data["tasks"] == []


def test_unknown_item_callback(env):
    fr, ft = env
    call(tap("x:2026-11-26:h:nope"))
    assert ft.answered == ["cb"] and ft.edited == []


def test_garbage_callback(env):
    fr, ft = env
    call(tap("garbage"))
    assert ft.answered == ["cb"]


def test_add(env):
    fr, ft = env
    call(msg("/add tomorrow Прочитати статтю"))
    task = fr.data["tasks"][-1]
    assert task["date"] == "2026-11-27" and task["title"] == "Прочитати статтю"
    assert len(f"x:2026-11-27:t:{task['id']}".encode()) <= 64
    call(msg("/add"))
    assert "Формат" in ft.sent[-1][1]


def test_export(env):
    fr, ft = env
    do_import(fr, ft)
    call(msg("/export"))
    filename, content = ft.documents[-1]
    exported = json.loads(content)
    assert filename.endswith(".json") and len(exported["tasks"]) == 2 and "days" in exported


def test_other_views_do_not_crash(env):
    fr, ft = env
    do_import(fr, ft)
    for cmd in ("/yesterday", "/week", "/streak", "/goals", "/help", "/nonsense", "/today@PlanABot"):
        call(msg(cmd))
    assert not any(t == views.ERROR for _, t, _ in ft.sent)


# ---------- note of the day + scheduler ----------

def test_evening_then_note(env):
    fr, ft = env
    do_import(fr, ft)
    scheduler_handler.lambda_handler({"kind": "evening"}, None)
    assert "Сьогодні ще нічого" in ft.sent[-2][1]
    assert ft.sent[-1][1] == views.NOTE_QUESTION

    call(msg("Зрозумів, що кеш — це компроміс"))
    assert fr.data["days"]["2026-11-26"]["note"] == "Зрозумів, що кеш — це компроміс"
    assert ft.sent[-1][1] == views.NOTE_SAVED

    call(msg("ще текст"))  # no longer awaiting a note
    assert ft.sent[-1][1] == views.UNKNOWN


def test_evening_active_day_only_asks_note(env):
    fr, ft = env
    fr.data["days"]["2026-11-26"] = {"done": ["h:h1"], "note": None}
    scheduler_handler.lambda_handler({"kind": "evening"}, None)
    assert [t for _, t, _ in ft.sent] == [views.NOTE_QUESTION]


def test_late_only_when_yesterday_missed_and_today_empty(env):
    fr, ft = env
    scheduler_handler.lambda_handler({"kind": "late"}, None)
    assert "🚨" in ft.sent[-1][1]

    ft.sent.clear()
    fr.data["days"]["2026-11-25"] = {"done": ["h:h1"]}
    scheduler_handler.lambda_handler({"kind": "late"}, None)
    assert ft.sent == []

    fr.data["days"]["2026-11-25"] = {"done": []}
    fr.data["days"]["2026-11-26"] = {"done": ["h:h1"]}
    scheduler_handler.lambda_handler({"kind": "late"}, None)
    assert ft.sent == []


def test_morning_and_weekly(env):
    fr, ft = env
    do_import(fr, ft)
    assert scheduler_handler.lambda_handler({"kind": "morning"}, None)["ok"]
    assert "Доброго ранку" in ft.sent[-1][1] and ft.sent[-1][2]
    assert scheduler_handler.lambda_handler({"kind": "weekly"}, None)["ok"]
    assert "Тижневий звіт" in ft.sent[-1][1]


def test_unknown_kind_does_not_raise(env):
    assert scheduler_handler.lambda_handler({"kind": "nope"}, None)["ok"] is False
