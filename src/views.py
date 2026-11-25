"""Message texts (HTML parse mode) and inline keyboards.

Every function returns (text, reply_markup_or_None).
"""

from datetime import timedelta
from html import escape

import core

HELP = (
    "Привіт! Я PlanA — трекер звичок, задач і цілей.\n\n"
    "/today — план на сьогодні\n"
    "/yesterday — відмітити вчорашнє\n"
    "/week — підсумок тижня\n"
    "/streak — серія і карта активності\n"
    "/goals — цілі і прогрес\n"
    "/add &lt;дата&gt; &lt;назва&gt; — додати задачу (today, tomorrow або YYYY-MM-DD)\n"
    "/import — завантажити plan.json\n"
    "/export — бекап усіх даних"
)

NOTE_QUESTION = "📝 Що ти сьогодні зрозумів? Відповідай одним реченням."
NOTE_SAVED = "Записав ✍️"
IMPORT_WAITING = "Надішли plan.json документом. Звички, задачі, цілі й мінімуми буде замінено, історія днів лишиться."
ERROR = "Щось пішло не так 😕 Спробуй ще раз."
UNKNOWN = "Не розумію 🤔 /start — список команд."


def start_view():
    return HELP, None


def _keyboard(state):
    """One button per task/habit. Pressing it toggles the item for that day."""
    rows = []
    for item in state["items"]:
        label = item["title"]
        if item["overdue_from"]:
            label += f" · ⏳ з {core.fmt_day(core.parse_date(item['overdue_from']))}"
        mark = "✅" if item["done"] else "⬜"
        data = f"x:{state['date']}:{item['kind']}:{item['id']}"
        rows.append([{"text": f"{mark} {label}", "callback_data": data}])
    return {"inline_keyboard": rows} if rows else None


def day_keyboard(data, d):
    return _keyboard(core.day_state(data, d, d))


def day_view(data, d, today, header=None):
    """/today, /yesterday and the morning message."""
    if header is None:
        if d == today:
            header = f"<b>Сьогодні, {core.fmt_day(d)}</b>"
        elif d == today - timedelta(days=1):
            header = f"<b>Вчора, {core.fmt_day(d)}</b>"
        else:
            header = f"<b>{core.fmt_day(d)}</b>"

    state = core.day_state(data, d, today)
    lines = [
        header,
        f"🔥 Серія: {core.plural_days(state['streak'])}",
        f"🎯 Мінімум: {escape(state['minimum'])}",
    ]
    if state["total"]:
        lines.append(f"Виконано: {state['done']}/{state['total']}")
    else:
        lines.append("\nНа цей день нічого не заплановано. /import щоб завантажити план.")
    return "\n".join(lines), _keyboard(state)


def morning_view(data, today):
    tasks = core.tasks_for_day(data["tasks"], data["days"], today)
    header = "☀️ <b>Доброго ранку.</b> Сьогодні:"
    if tasks:
        header += "\n" + "\n".join(f"• {escape(t['title'])}" for t, _ in tasks)
    else:
        header += " задач немає, лише звички."
    header += "\n"
    return day_view(data, today, today, header=header)


def evening_empty_view(data, today):
    text = f"🌙 Сьогодні ще нічого. Мінімум: {escape(core.minimum_for(data['minimums'], today))}"
    return text, day_keyboard(data, today)


def late_view(data, today):
    text = (
        "🚨 Вчора пропуск. Якщо сьогодні нічого — серія згорить опівночі.\n"
        f"Мінімум: {escape(core.minimum_for(data['minimums'], today))}"
    )
    return text, day_keyboard(data, today)


def week_view(data, today, with_notes=False):
    s = core.week_summary(data, today)
    lines = [
        f"<b>Тиждень {s['start']:%d.%m}–{s['end']:%d.%m}</b>",
        f"Активні дні: {s['active']}/7",
        f"🔥 Серія: {core.plural_days(core.streak(data['days'], today))}",
    ]
    if s["by_area"]:
        lines.append("\n<b>Виконано по сферах</b>")
        order = core.AREAS + sorted(a for a in s["by_area"] if a not in core.AREAS)
        for area in order:
            if area in s["by_area"]:
                lines.append(f"• {escape(area)}: {s['by_area'][area]}")
    else:
        lines.append("\nЦього тижня ще нічого не виконано.")
    lines.append("\n" + core.heatmap(data["days"], today))
    if with_notes:
        lines.append("\n<b>Нотатки тижня</b>")
        if s["notes"]:
            lines += [f"• {core.fmt_day(d)}: {escape(note)}" for d, note in s["notes"]]
        else:
            lines.append("нотаток немає")
    return "\n".join(lines), None


def weekly_report_view(data, today):
    text, _ = week_view(data, today, with_notes=True)
    return "📊 <b>Тижневий звіт</b>\n\n" + text, None


def streak_view(data, today):
    days = data["days"]
    lines = [
        f"🔥 Серія: {core.plural_days(core.streak(days, today))}",
        f"🏆 Найкраща: {core.plural_days(core.best_streak(days, today))}",
        "",
        core.heatmap(days, today),
        "",
        "⬜ 0 · 🟨 1–2 · 🟩 3+ · ▫️ поза історією",
    ]
    return "\n".join(lines), None


def goals_view(data):
    goals = data["goals"]
    if not goals:
        return "Цілей ще немає. Додай їх через /import.", None

    horizons = core.HORIZONS + sorted({g["horizon"] for g in goals} - set(core.HORIZONS))
    lines = []
    for horizon in horizons:
        group = [g for g in goals if g["horizon"] == horizon]
        if not group:
            continue
        lines.append(f"\n<b>{escape(horizon or 'Без горизонту')}</b>")
        for g in sorted(group, key=lambda g: (g.get("deadline") or "9999", g["title"])):
            done, total = core.goal_progress(g, data["tasks"], data["days"])
            title = f"{escape(g['title'])} <i>[{escape(g['area'])}]</i>"
            if g.get("deadline"):
                try:
                    title += f" до {core.parse_date(g['deadline']):%d.%m}"
                except ValueError:
                    pass
            lines.append(title)
            lines.append(f"<code>{core.progress_bar(done, total)}</code> ({done}/{total})")
    return "🎯 <b>Цілі</b>" + "\n".join(lines), None
