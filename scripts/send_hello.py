"""Check the bot token: sends "hello" to OWNER_CHAT_ID.

    python scripts/send_hello.py
"""

import _env

BOT_TOKEN, OWNER_CHAT_ID = _env.require("BOT_TOKEN", "OWNER_CHAT_ID")

import telegram  # noqa: E402

telegram.send_message(int(OWNER_CHAT_ID), "hello 👋 PlanA на зв'язку")
print("Sent. Check Telegram.")
