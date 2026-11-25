"""Minimal Telegram Bot API client on urllib (no dependencies).

The bot token is part of every API URL, so it must never end up in logs or
exception messages. Errors are raised as TelegramError with the method name
and Telegram's description only.
"""

import json
import os
import urllib.error
import urllib.request
import uuid

TIMEOUT = 10


class TelegramError(Exception):
    pass


def _token():
    return os.environ["BOT_TOKEN"]


def _request(method, data, headers):
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            description = json.loads(e.read()).get("description", "")
        except Exception:
            description = ""
        raise TelegramError(f"{method}: HTTP {e.code} {description}") from None
    except urllib.error.URLError as e:
        raise TelegramError(f"{method}: network error {e.reason}") from None
    if not body.get("ok"):
        raise TelegramError(f"{method}: {body.get('description', 'unknown error')}")
    return body["result"]


def call(method, **params):
    payload = {k: v for k, v in params.items() if v is not None}
    data = json.dumps(payload).encode()
    return _request(method, data, {"Content-Type": "application/json"})


def send_message(chat_id, text, reply_markup=None):
    return call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        link_preview_options={"is_disabled": True},
    )


def edit_message(chat_id, message_id, text, reply_markup=None):
    try:
        return call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options={"is_disabled": True},
        )
    except TelegramError as e:
        # Same text and keyboard -> Telegram refuses; nothing to do.
        if "message is not modified" in str(e):
            return None
        raise


def answer_callback(callback_query_id, text=None):
    return call("answerCallbackQuery", callback_query_id=callback_query_id, text=text)


def send_document(chat_id, filename, content, caption=None):
    """Upload `content` (bytes) as a file via multipart/form-data."""
    boundary = uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    field("chat_id", str(chat_id))
    if caption:
        field("caption", caption)
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return _request(
        "sendDocument",
        b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def get_file(file_id, max_bytes=1_000_000):
    """Download a file the user sent. Returns bytes."""
    info = call("getFile", file_id=file_id)
    if info.get("file_size", 0) > max_bytes:
        raise TelegramError("getFile: file is too large")
    url = f"https://api.telegram.org/file/bot{_token()}/{info['file_path']}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return resp.read(max_bytes + 1)[:max_bytes]
    except urllib.error.URLError:
        raise TelegramError("file download failed") from None
