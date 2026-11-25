"""Print every bot message for a plan file, without AWS or Telegram.

    python scripts/preview.py [plan.json] [YYYY-MM-DD]

Some fake history is generated so streaks and the heatmap are not empty.
"""

import json
import sys
from datetime import timedelta

import _env  # noqa: F401  (puts src/ on sys.path)

import core
import views


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(_env.ROOT / "plan.example.json")
    today = core.parse_date(sys.argv[2]) if len(sys.argv) > 2 else core.today_kyiv()
    with open(path, encoding="utf-8") as f:
        plan = core.validate_plan(json.load(f))

    # Fake history: habits on most days since start, a note now and then.
    days = {}
    d = core.START_DATE
    i = 0
    while d < today:
        if i % 4 != 2:
            done = [f"h:{h['id']}" for h in plan["habits"][: 1 + i % 3]]
            days[core.key(d)] = {"done": done, "note": "Тестова нотатка" if i % 3 == 0 else None}
        d += timedelta(days=1)
        i += 1
    if plan["tasks"]:
        days.setdefault(plan["tasks"][0]["date"], {"done": [], "note": None})["done"].append(
            f"t:{plan['tasks'][0]['id']}"
        )

    data = {**plan, "days": days, "state": {}}
    yesterday = today - timedelta(days=1)
    screens = {
        "/start": views.start_view(),
        "/today": views.day_view(data, today, today),
        "/yesterday": views.day_view(data, yesterday, today),
        "/week": views.week_view(data, today),
        "/streak": views.streak_view(data, today),
        "/goals": views.goals_view(data),
        "morning": views.morning_view(data, today),
        "evening (empty day)": views.evening_empty_view(data, today),
        "late": views.late_view(data, today),
        "weekly": views.weekly_report_view(data, today),
    }
    for name, (text, keyboard) in screens.items():
        print(f"===== {name} =====")
        print(text)
        if keyboard:
            for row in keyboard["inline_keyboard"]:
                for b in row:
                    print(f"  [{b['text']}]  ({b['callback_data']})")
        print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
