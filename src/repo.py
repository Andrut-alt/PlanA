"""DynamoDB access. One table, PK = "USER#<chat_id>", SK = record type.

There are only hundreds of records, so every request simply loads everything
with one Query and works with plain Python dicts.
"""

import os
from decimal import Decimal

import boto3

import core

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def _pk(chat_id):
    return f"USER#{chat_id}"


def _from_dynamo(value):
    """Decimal -> int/float, recursively."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    return value


def _to_dynamo(value):
    """float -> Decimal, recursively (boto3 rejects floats)."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    return value


def _query_all(chat_id, **extra):
    items = []
    kwargs = {
        "KeyConditionExpression": "PK = :pk",
        "ExpressionAttributeValues": {":pk": _pk(chat_id)},
        **extra,
    }
    while True:
        resp = table().query(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def load(chat_id):
    """Everything for one user as plain dicts (shapes are described in core.py)."""
    data = {"habits": [], "tasks": [], "goals": [], "minimums": {}, "days": {}, "state": {}}
    for raw in _query_all(chat_id):
        item = _from_dynamo(raw)
        sk = item.pop("SK")
        item.pop("PK", None)
        kind, _, ident = sk.partition("#")
        if kind == "HABIT":
            data["habits"].append({"id": ident, **item})
        elif kind == "TASK":
            data["tasks"].append({"id": ident, **item})
        elif kind == "GOAL":
            data["goals"].append({"id": ident, **item})
        elif kind == "MIN":
            data["minimums"][ident] = item.get("text", "")
        elif kind == "DAY":
            data["days"][ident] = {"done": item.get("done") or [], "note": item.get("note")}
        elif kind == "STATE":
            data["state"] = item
    return data


def save_day_done(chat_id, day_key, done):
    table().update_item(
        Key={"PK": _pk(chat_id), "SK": f"DAY#{day_key}"},
        UpdateExpression="SET done = :d",
        ExpressionAttributeValues={":d": done},
    )


def save_note(chat_id, day_key, note):
    table().update_item(
        Key={"PK": _pk(chat_id), "SK": f"DAY#{day_key}"},
        UpdateExpression="SET note = :n",
        ExpressionAttributeValues={":n": note},
    )


# ---------- actions shared by the bot and the future Mini App API ----------

def toggle_item(chat_id, day_key, kind, item_id):
    """Tick/untick a task or habit. Returns fresh data, or None if the item is unknown."""
    data = load(chat_id)
    if not core.item_exists(data, kind, item_id):
        return None
    save_key, done = core.toggle(data["days"], day_key, kind, item_id)
    save_day_done(chat_id, save_key, done)
    data["days"].setdefault(save_key, {"done": [], "note": None})["done"] = done
    return data


def save_pending_note(chat_id, text):
    """Store `text` as the note the evening reminder asked for. Returns the day key or None."""
    day_key = load(chat_id)["state"].get("awaiting_note_for")
    if not day_key:
        return None
    save_note(chat_id, day_key, text[:1000])
    set_state(chat_id, awaiting_note_for=None)
    return day_key


def set_state(chat_id, **fields):
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    table().update_item(
        Key={"PK": _pk(chat_id), "SK": "STATE"},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def add_task(chat_id, task):
    fields = {k: v for k, v in task.items() if k != "id"}
    table().put_item(Item=_to_dynamo({"PK": _pk(chat_id), "SK": f"TASK#{task['id']}", **fields}))


def replace_plan(chat_id, plan):
    """Replace habits/tasks/goals/minimums. DAY# and STATE records stay untouched."""
    pk = _pk(chat_id)
    new_items = []
    for prefix, items in (("HABIT", plan["habits"]), ("TASK", plan["tasks"]), ("GOAL", plan["goals"])):
        for item in items:
            fields = {k: v for k, v in item.items() if k != "id"}
            new_items.append(_to_dynamo({"PK": pk, "SK": f"{prefix}#{item['id']}", **fields}))
    for day_key, text in plan["minimums"].items():
        new_items.append({"PK": pk, "SK": f"MIN#{day_key}", "text": text})
    new_sks = {item["SK"] for item in new_items}

    old_keys = _query_all(chat_id, ProjectionExpression="PK, SK")
    with table().batch_writer() as batch:
        # Delete only records that are not overwritten: a batch must not touch one key twice.
        for k in old_keys:
            if k["SK"].split("#", 1)[0] in ("HABIT", "TASK", "GOAL", "MIN") and k["SK"] not in new_sks:
                batch.delete_item(Key={"PK": k["PK"], "SK": k["SK"]})
        for item in new_items:
            batch.put_item(Item=item)
