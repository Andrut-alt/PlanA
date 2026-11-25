"""Pure business logic: dates, streaks, overdue tasks, heatmap, goal progress.

No AWS, no Telegram, no I/O here, so everything is easy to test.

Data shapes used across the project:
    days:     {"YYYY-MM-DD": {"done": ["t:<id>", "h:<id>", ...], "note": str | None}}
    tasks:    [{"id", "date", "title", "area", "goal", "xp", "min", "milestone"}]
    habits:   [{"id", "title", "area", "xp", "order"}]
    goals:    [{"id", "title", "area", "horizon", "deadline", "criterion"}]
    minimums: {"YYYY-MM-DD": "text"}
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
START_DATE = date(2026, 11, 23)
ONE_DAY = timedelta(days=1)

AREAS = ["Інженер", "Англійська", "Тіло", "Розум", "Життя"]
HORIZONS = ["Грудень", "3 міс", "6 міс", "12 міс"]
DEFAULT_AREA = "Інженер"
DEFAULT_MINIMUM = "1 будь-який пункт плану"

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
MONTHS = ["Січ", "Лют", "Бер", "Кві", "Тра", "Чер", "Лип", "Сер", "Вер", "Жов", "Лис", "Гру"]

# Ids end up in callback data "x:<YYYY-MM-DD>:<t|h>:<id>", which must fit in 64 bytes.
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


# ---------- dates ----------

def today_kyiv(now=None):
    """Current date in Kyiv. `now` is an aware datetime (handy for tests)."""
    now = now or datetime.now(KYIV)
    return now.astimezone(KYIV).date()


def key(d):
    return d.isoformat()


def parse_date(s):
    return date.fromisoformat(s)


def fmt_day(d):
    """'Пн 24.11'"""
    return f"{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}"


def week_dates(d):
    """Monday..Sunday of the week that contains `d`."""
    monday = d - timedelta(days=d.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def parse_add_date(arg, today):
    """'today' / 'tomorrow' / 'YYYY-MM-DD' -> date, or None if not valid."""
    arg = arg.strip().lower()
    if arg in ("today", "сьогодні"):
        return today
    if arg in ("tomorrow", "завтра"):
        return today + ONE_DAY
    try:
        return parse_date(arg)
    except ValueError:
        return None


# ---------- days and streaks ----------

def done_count(day):
    return len((day or {}).get("done") or [])


def is_active(day):
    """A day is active when at least one item (task or habit) is done."""
    return done_count(day) > 0


def streak(days, today):
    """Current streak with the "never miss twice" rule.

    Count back from today: an active day adds 1, a single missed day is
    forgiven, two missed days in a row end the streak. Today is still open,
    so an empty today is not a miss yet.
    """
    d = today
    if not is_active(days.get(key(d))):
        d -= ONE_DAY
    count = 0
    misses = 0
    while d >= START_DATE:
        if is_active(days.get(key(d))):
            count += 1
            misses = 0
        else:
            misses += 1
            if misses >= 2:
                break
        d -= ONE_DAY
    return count


def best_streak(days, today):
    """Max streak over the whole history, same rule as `streak`."""
    best = current = misses = 0
    d = START_DATE
    while d <= today:
        if is_active(days.get(key(d))):
            current += 1
            misses = 0
        elif d != today:  # empty today is not a miss yet
            misses += 1
            if misses >= 2:
                current = 0
        best = max(best, current)
        d += ONE_DAY
    return best


def missed(days, d):
    """True if `d` is a past-start day with nothing done."""
    return d >= START_DATE and not is_active(days.get(key(d)))


# ---------- tasks ----------

def task_done_on(task_id, days):
    """Date key of the day where the task is marked done, or None."""
    token = f"t:{task_id}"
    for day_key, day in days.items():
        if token in (day.get("done") or []):
            return day_key
    return None


def overdue_tasks(tasks, days, today):
    """Tasks dated before today that are not done on any day, oldest first."""
    today_key = key(today)
    result = [
        t for t in tasks
        if t["date"] < today_key and task_done_on(t["id"], days) is None
    ]
    return sorted(result, key=lambda t: t["date"])


def tasks_for_day(tasks, days, d):
    """Tasks to show for day `d`: [(task, is_overdue), ...].

    - tasks dated `d`;
    - older tasks that are still not done (overdue);
    - older tasks that were completed on `d` (so the tick stays visible).
    """
    d_key = key(d)
    result = []
    for t in sorted(tasks, key=lambda t: (t["date"], t.get("title", ""))):
        if t["date"] == d_key:
            result.append((t, False))
        elif t["date"] < d_key:
            done_on = task_done_on(t["id"], days)
            if done_on is None or done_on == d_key:
                result.append((t, True))
    return result


def is_item_done(days, d, kind, item_id):
    """Is the item ticked for day `d`? Tasks count as done if done on any day."""
    if kind == "t":
        return task_done_on(item_id, days) is not None
    return f"h:{item_id}" in (days.get(key(d), {}).get("done") or [])


def toggle(days, d_key, kind, item_id):
    """Toggle an item. Returns (day_key_to_save, new_done_list).

    A task that is already done somewhere is unticked on THAT day.
    Otherwise the item is ticked on the day the button belongs to.
    """
    token = f"{kind}:{item_id}"
    if kind == "t":
        where = task_done_on(item_id, days)
        if where is not None:
            return where, [x for x in days[where].get("done", []) if x != token]
    done = list(days.get(d_key, {}).get("done") or [])
    if token in done:
        done.remove(token)
    else:
        done.append(token)
    return d_key, done


def minimum_for(minimums, d):
    return minimums.get(key(d)) or DEFAULT_MINIMUM


def item_exists(data, kind, item_id):
    items = data["tasks"] if kind == "t" else data["habits"] if kind == "h" else []
    return any(i["id"] == item_id for i in items)


def day_state(data, d, today):
    """Everything needed to render one day, as plain JSON-friendly data.

    Used by the Telegram views now and by the Mini App API later.
    """
    days = data["days"]
    items = []
    for task, overdue in tasks_for_day(data["tasks"], days, d):
        items.append({
            "kind": "t",
            "id": task["id"],
            "title": task["title"],
            "area": task.get("area") or DEFAULT_AREA,
            "done": is_item_done(days, d, "t", task["id"]),
            "overdue_from": task["date"] if overdue else None,
        })
    for habit in sorted(data["habits"], key=lambda h: (h.get("order", 0), h["title"])):
        items.append({
            "kind": "h",
            "id": habit["id"],
            "title": habit["title"],
            "area": habit.get("area") or DEFAULT_AREA,
            "done": is_item_done(days, d, "h", habit["id"]),
            "overdue_from": None,
        })
    return {
        "date": key(d),
        "items": items,
        "done": sum(1 for i in items if i["done"]),
        "total": len(items),
        "minimum": minimum_for(data["minimums"], d),
        "note": (days.get(key(d)) or {}).get("note"),
        "streak": streak(days, today),
    }


# ---------- goals ----------

def goal_progress(goal, tasks, days):
    """(done, total) for tasks linked to the goal."""
    linked = [t for t in tasks if t.get("goal") == goal["id"]]
    done = sum(1 for t in linked if task_done_on(t["id"], days) is not None)
    return done, len(linked)


def progress_bar(done, total, width=10):
    """'▓▓▓░░░░░░░ 30%'"""
    pct = round(100 * done / total) if total else 0
    filled = round(width * done / total) if total else 0
    return "▓" * filled + "░" * (width - filled) + f" {pct}%"


# ---------- heatmap ----------

def heat_cell(days, d, today):
    if d > today or d < START_DATE:
        return "▫️"
    n = done_count(days.get(key(d)))
    if n == 0:
        return "⬜"
    if n <= 2:
        return "🟨"
    return "🟩"


def heatmap(days, today, weeks=12):
    """Emoji activity map: rows Mon..Sun, columns are the last `weeks` weeks.

    Returns a multi-line string with a month header on top. Telegram fonts are
    proportional, so the header alignment is approximate.
    """
    last_monday = today - timedelta(days=today.weekday())
    mondays = [last_monday - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]

    # Month header: label the first column and every column containing the 1st of a month.
    em = " "  # em space is roughly as wide as one emoji
    header = [em, em]  # room for the "Пн " row label
    skip = 0
    for i, monday in enumerate(mondays):
        sunday = monday + timedelta(days=6)
        label = None
        if i == 0:
            label = MONTHS[monday.month - 1]
        elif sunday.month != monday.month or monday.day == 1:
            label = MONTHS[sunday.month - 1]
        if label:
            header.append(label)
            skip = 1  # a 3-letter label is wider than one emoji
        elif skip:
            skip -= 1
        else:
            header.append(em)

    lines = ["".join(header).rstrip()]
    for row in range(7):
        cells = "".join(heat_cell(days, m + timedelta(days=row), today) for m in mondays)
        lines.append(f"{WEEKDAYS[row]} {cells}")
    return "\n".join(lines)


# ---------- week summary ----------

def week_summary(data, today):
    """Numbers for the weekly report."""
    days = data["days"]
    dates = [d for d in week_dates(today) if d <= today]
    tasks_by_id = {t["id"]: t for t in data["tasks"]}
    habits_by_id = {h["id"]: h for h in data["habits"]}

    by_area = {}
    for d in dates:
        for token in days.get(key(d), {}).get("done") or []:
            kind, _, item_id = token.partition(":")
            item = (tasks_by_id if kind == "t" else habits_by_id).get(item_id)
            area = (item or {}).get("area") or DEFAULT_AREA
            by_area[area] = by_area.get(area, 0) + 1

    notes = [(d, days[key(d)]["note"]) for d in dates if (days.get(key(d)) or {}).get("note")]
    return {
        "start": week_dates(today)[0],
        "end": week_dates(today)[6],
        "active": sum(1 for d in dates if is_active(days.get(key(d)))),
        "by_area": by_area,
        "notes": notes,
    }


# ---------- import validation ----------

def validate_plan(plan):
    """Check and normalise a plan.json dict. Raises ValueError with a Ukrainian message."""
    if not isinstance(plan, dict):
        raise ValueError("Очікую JSON-об'єкт з ключами habits, goals, tasks, minimums.")

    def check_list(name):
        items = plan.get(name, [])
        if not isinstance(items, list):
            raise ValueError(f"«{name}» має бути списком.")
        seen = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"{name}[{i}]: очікую об'єкт.")
            item_id = str(item.get("id", ""))
            if not ID_RE.match(item_id):
                raise ValueError(f"{name}[{i}]: id має бути 1–40 символів A-Z, a-z, 0-9, _ або -.")
            if item_id in seen:
                raise ValueError(f"{name}: id «{item_id}» повторюється.")
            seen.add(item_id)
            if not str(item.get("title", "")).strip():
                raise ValueError(f"{name}[{i}]: немає title.")
        return items

    habits = check_list("habits")
    goals = check_list("goals")
    tasks = check_list("tasks")

    for t in tasks:
        try:
            parse_date(str(t.get("date", "")))
        except ValueError:
            raise ValueError(f"tasks «{t['id']}»: дата має бути у форматі YYYY-MM-DD.") from None

    minimums = plan.get("minimums", {})
    if not isinstance(minimums, dict):
        raise ValueError("«minimums» має бути об'єктом {\"YYYY-MM-DD\": \"текст\"}.")
    for k in minimums:
        try:
            parse_date(k)
        except ValueError:
            raise ValueError(f"minimums: «{k}» — не дата YYYY-MM-DD.") from None

    return {
        "habits": [
            {
                "id": str(h["id"]),
                "title": str(h["title"]).strip(),
                "area": h.get("area") or DEFAULT_AREA,
                "xp": int(h.get("xp") or 0),
                "order": int(h.get("order", i)),
            }
            for i, h in enumerate(habits)
        ],
        "goals": [
            {
                "id": str(g["id"]),
                "title": str(g["title"]).strip(),
                "area": g.get("area") or DEFAULT_AREA,
                "horizon": g.get("horizon") or "",
                "deadline": g.get("deadline") or "",
                "criterion": g.get("criterion") or "",
            }
            for g in goals
        ],
        "tasks": [
            {
                "id": str(t["id"]),
                "date": str(t["date"]),
                "title": str(t["title"]).strip(),
                "area": t.get("area") or DEFAULT_AREA,
                "goal": t.get("goal") or "",
                "xp": int(t.get("xp") or 0),
                "min": int(t.get("min") or 0),
                "milestone": bool(t.get("milestone", False)),
            }
            for t in tasks
        ],
        "minimums": {k: str(v) for k, v in minimums.items()},
    }


def plural_days(n):
    """1 день, 2 дні, 5 днів."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дні"
    return f"{n} днів"
