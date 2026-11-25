from datetime import date, datetime, timedelta, timezone

import pytest

import core
from core import START_DATE

D = timedelta(days=1)


def make_days(pattern, last_day):
    """'✅✅⬜✅✅' -> days dict, the last symbol is `last_day`."""
    days = {}
    first = last_day - D * (len(pattern) - 1)
    for i, ch in enumerate(pattern):
        d = first + D * i
        days[core.key(d)] = {"done": ["h:x"] if ch == "✅" else [], "note": None}
    return days


# Run all streak examples well after START_DATE so history start does not interfere.
TODAY = START_DATE + D * 20


# ---------- streak: examples from the spec ----------

def test_streak_single_gap_is_forgiven():
    assert core.streak(make_days("✅✅⬜✅✅", TODAY), TODAY) == 4


def test_streak_two_gaps_break():
    assert core.streak(make_days("✅✅⬜⬜✅", TODAY), TODAY) == 1


def test_streak_empty_today_is_still_open():
    days = make_days("✅✅✅⬜", TODAY - D)  # yesterday missed, today has no record
    assert core.streak(days, TODAY) == 3


def test_streak_yesterday_and_today_empty_with_earlier_gap():
    days = make_days("✅✅⬜⬜", TODAY - D)
    assert core.streak(days, TODAY) == 0


def test_streak_nothing():
    assert core.streak({}, TODAY) == 0


def test_streak_stops_at_start_date():
    days = make_days("✅✅✅", START_DATE + D * 2)
    days[core.key(START_DATE - D)] = {"done": ["h:x"]}  # before start: ignored
    assert core.streak(days, START_DATE + D * 2) == 3


# ---------- best streak ----------

def test_best_streak():
    days = make_days("✅✅✅⬜✅⬜⬜✅✅", TODAY)
    assert core.best_streak(days, TODAY) == 4
    assert core.streak(days, TODAY) == 2


def test_best_streak_ignores_open_today():
    days = make_days("✅✅⬜✅", TODAY - D)
    assert core.best_streak(days, TODAY) == 3


@pytest.mark.parametrize("pattern", ["✅✅⬜✅✅", "✅✅⬜⬜✅", "⬜✅⬜✅⬜⬜✅✅✅", "✅"])
def test_best_streak_at_least_current(pattern):
    days = make_days(pattern, TODAY)
    assert core.best_streak(days, TODAY) >= core.streak(days, TODAY)


# ---------- dates ----------

def test_today_kyiv_crosses_midnight_before_utc():
    # 22:30 UTC on Nov 25 is already Nov 26 in Kyiv (UTC+2 in winter).
    now = datetime(2026, 11, 25, 22, 30, tzinfo=timezone.utc)
    assert core.today_kyiv(now) == date(2026, 11, 26)


def test_fmt_day():
    assert core.fmt_day(date(2026, 11, 24)) == "Вт 24.11"
    assert core.fmt_day(date(2026, 11, 23)) == "Пн 23.11"


def test_parse_add_date():
    today = date(2026, 11, 26)
    assert core.parse_add_date("today", today) == today
    assert core.parse_add_date("tomorrow", today) == date(2026, 11, 27)
    assert core.parse_add_date("2026-12-01", today) == date(2026, 12, 1)
    assert core.parse_add_date("someday", today) is None


# ---------- tasks ----------

TASKS = [
    {"id": "t1", "date": "2026-11-23", "title": "Old done"},
    {"id": "t2", "date": "2026-11-24", "title": "Old open"},
    {"id": "t3", "date": "2026-11-26", "title": "Today"},
    {"id": "t4", "date": "2026-11-27", "title": "Tomorrow"},
    {"id": "t5", "date": "2026-11-23", "title": "Old done today"},
]
DAYS = {
    "2026-11-23": {"done": ["t:t1", "h:h1"]},
    "2026-11-26": {"done": ["t:t5"]},
}
T = date(2026, 11, 26)


def test_task_done_on():
    assert core.task_done_on("t1", DAYS) == "2026-11-23"
    assert core.task_done_on("t2", DAYS) is None


def test_overdue_tasks():
    assert [t["id"] for t in core.overdue_tasks(TASKS, DAYS, T)] == ["t2"]


def test_tasks_for_day():
    result = [(t["id"], overdue) for t, overdue in core.tasks_for_day(TASKS, DAYS, T)]
    assert ("t3", False) in result
    assert ("t2", True) in result
    assert ("t5", True) in result  # completed today, still visible today
    assert all(i not in ("t1", "t4") for i, _ in result)


def test_toggle_task_on_and_off():
    days = {}
    day_key, done = core.toggle(days, "2026-11-26", "t", "t3")
    assert (day_key, done) == ("2026-11-26", ["t:t3"])
    days[day_key] = {"done": done}
    # Pressing again from another day's view removes it from the day where it is.
    day_key, done = core.toggle(days, "2026-11-25", "t", "t3")
    assert (day_key, done) == ("2026-11-26", [])


def test_toggle_habit_is_per_day():
    days = {"2026-11-25": {"done": ["h:h1"]}}
    assert core.toggle(days, "2026-11-26", "h", "h1") == ("2026-11-26", ["h:h1"])
    assert core.toggle(days, "2026-11-25", "h", "h1") == ("2026-11-25", [])


# ---------- goals ----------

def test_goal_progress_and_bar():
    tasks = [{"id": f"t{i}", "date": "2026-11-23", "goal": "g1"} for i in range(10)]
    tasks.append({"id": "other", "date": "2026-11-23", "goal": "g2"})
    days = {"2026-11-23": {"done": ["t:t0", "t:t1", "t:other"]}, "2026-11-24": {"done": ["t:t2"]}}
    done, total = core.goal_progress({"id": "g1"}, tasks, days)
    assert (done, total) == (3, 10)
    assert core.progress_bar(done, total) == "▓▓▓░░░░░░░ 30%"
    assert core.progress_bar(0, 0) == "░░░░░░░░░░ 0%"


# ---------- heatmap ----------

def test_heatmap_shape_and_cells():
    today = date(2026, 11, 26)  # Thursday
    days = {
        "2026-11-23": {"done": ["h:a"]},                     # Mon: 1 -> yellow
        "2026-11-24": {"done": ["h:a", "h:b", "t:c"]},       # Tue: 3 -> green
    }
    lines = core.heatmap(days, today, weeks=12).split("\n")
    assert len(lines) == 8  # month header + 7 weekdays
    rows = lines[1:]
    assert rows[0].startswith("Пн ") and rows[6].startswith("Нд ")
    # Last column = current week.
    assert rows[0].endswith("🟨")
    assert rows[1].endswith("🟩")
    assert rows[2].endswith("⬜")   # Wed, empty
    assert rows[3].endswith("⬜")   # Thu = today, empty
    assert rows[4].endswith("▫️")  # Fri, future
    assert rows[0].count("▫️") == 11  # weeks before start


def test_heatmap_month_header():
    header = core.heatmap({}, date(2026, 11, 26)).split("\n")[0]
    assert "Вер" in header and "Жов" in header and "Лис" in header


# ---------- week ----------

def test_week_summary():
    data = {
        "tasks": [{"id": "t1", "area": "Англійська"}],
        "habits": [{"id": "h1", "area": "Тіло"}],
        "days": {
            "2026-11-23": {"done": ["t:t1", "h:h1"], "note": "Зрозумів X"},
            "2026-11-25": {"done": ["h:h1"]},
            "2026-11-22": {"done": ["h:h1"]},  # previous week
        },
    }
    s = core.week_summary(data, date(2026, 11, 26))
    assert s["active"] == 2
    assert s["by_area"] == {"Англійська": 1, "Тіло": 2}
    assert s["notes"] == [(date(2026, 11, 23), "Зрозумів X")]


# ---------- import ----------

def test_validate_plan_ok():
    plan = core.validate_plan({
        "habits": [{"id": "h1", "title": "Зарядка"}],
        "goals": [],
        "tasks": [{"id": "t1", "date": "2026-11-23", "title": "Задача", "xp": 10}],
        "minimums": {"2026-11-23": "20 хв"},
    })
    assert plan["habits"][0]["area"] == core.DEFAULT_AREA
    assert plan["tasks"][0]["milestone"] is False


def test_validate_plan_ignores_rewards():
    plan = core.validate_plan({"habits": [], "rewards": [{"id": "r1", "title": "Кіно", "cost": 40}]})
    assert "rewards" not in plan


def test_day_state():
    data = {
        "tasks": TASKS, "days": DAYS, "minimums": {"2026-11-26": "20 хв"},
        "habits": [{"id": "h1", "title": "Зарядка", "area": "Тіло"}],
    }
    s = core.day_state(data, T, T)
    by_id = {i["id"]: i for i in s["items"]}
    assert s["date"] == "2026-11-26" and s["minimum"] == "20 хв"
    assert by_id["t2"]["overdue_from"] == "2026-11-24" and not by_id["t2"]["done"]
    assert by_id["t5"]["done"] and by_id["t3"]["overdue_from"] is None
    assert by_id["h1"]["kind"] == "h" and not by_id["h1"]["done"]
    assert (s["done"], s["total"]) == (1, 4)
    json_safe = __import__("json").dumps(s)  # must be serialisable for the future API
    assert json_safe


@pytest.mark.parametrize("bad", [
    [],
    {"tasks": [{"id": "t1", "date": "23.11.2026", "title": "x"}]},
    {"tasks": [{"id": "t 1", "date": "2026-11-23", "title": "x"}]},
    {"habits": [{"id": "h1", "title": "a"}, {"id": "h1", "title": "b"}]},
    {"habits": [{"id": "h1", "title": ""}]},
    {"minimums": {"tomorrow": "x"}},
])
def test_validate_plan_errors(bad):
    with pytest.raises(ValueError):
        core.validate_plan(bad)


def test_plural_days():
    assert [core.plural_days(n) for n in (0, 1, 2, 5, 11, 21, 22)] == [
        "0 днів", "1 день", "2 дні", "5 днів", "11 днів", "21 день", "22 дні",
    ]
