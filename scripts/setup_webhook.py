"""Point Telegram at the deployed Function URL and register the command menu.

    python scripts/setup_webhook.py <FunctionUrl>

The webhook is set on <FunctionUrl>/webhook (other paths return 404).

Reads BOT_TOKEN and WEBHOOK_SECRET from .env / environment, so secrets do
not end up in shell history.
"""

import sys

import _env

_env.require("BOT_TOKEN", "WEBHOOK_SECRET")

import os  # noqa: E402

import telegram  # noqa: E402

COMMANDS = [
    ("today", "План на сьогодні"),
    ("yesterday", "Відмітити вчорашнє"),
    ("week", "Підсумок тижня"),
    ("streak", "Серія і карта активності"),
    ("goals", "Цілі і прогрес"),
    ("add", "Додати задачу: /add tomorrow Назва"),
    ("import", "Завантажити plan.json"),
    ("export", "Бекап даних"),
    ("start", "Довідка"),
]


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("Usage: python scripts/setup_webhook.py https://<id>.lambda-url.eu-central-1.on.aws/")
    url = sys.argv[1].rstrip("/")
    if not url.endswith("/webhook"):
        url += "/webhook"
    telegram.call(
        "setWebhook",
        url=url,
        secret_token=os.environ["WEBHOOK_SECRET"],
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )
    telegram.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
    info = telegram.call("getWebhookInfo")
    print("Webhook set:", info.get("url"))
    print("Pending updates:", info.get("pending_update_count"), "| last error:", info.get("last_error_message"))


if __name__ == "__main__":
    main()
