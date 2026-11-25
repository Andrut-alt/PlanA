# PlanA

Особистий Telegram-бот для щоденних звичок, задач плану, цілей і серії днів з правилом «ніколи двічі».
AWS Lambda + DynamoDB + EventBridge Scheduler, Python 3.12, без бот-фреймворків. Повна специфікація — [SPEC.md](SPEC.md).

```
Telegram ──POST /webhook──► Lambda Function URL ──► webhook_handler ──► DynamoDB
EventBridge Scheduler (Europe/Kyiv) ──► scheduler_handler ──► Telegram
```

`webhook_handler` маршрутизує за шляхом: `POST /webhook` — оновлення Telegram, `/api/*` зарезервовано під API Mini App (версія 2) і поки віддає 404, як і будь-який інший шлях.
Дії «відмітити пункт», «зберегти нотатку», «стан дня» живуть у `repo.py` / `core.py` (`repo.toggle_item`, `repo.save_pending_note`, `core.day_state`), щоб API версії 2 викликало ті самі функції.

## Структура

| Файл | Що робить |
|---|---|
| `src/core.py` | чиста логіка: дати, серія, прострочені задачі, карта активності, прогрес цілей, валідація імпорту |
| `src/views.py` | тексти повідомлень і inline-клавіатури |
| `src/telegram.py` | Telegram Bot API на `urllib` |
| `src/repo.py` | DynamoDB (одна таблиця, `PK = USER#<chat_id>`) |
| `src/webhook_handler.py` | команди, кнопки, імпорт файлу, нотатки |
| `src/scheduler_handler.py` | нагадування: morning / evening / late / weekly |
| `template.yaml` | SAM: таблиця, 2 функції, Function URL, 4 розклади |
| `plan.example.json` | приклад плану для `/import` |
| `scripts/` | локальні утиліти: превʼю текстів, тест токена, налаштування webhook |

## Безпека (репозиторій публічний)

- Секрети (`BOT_TOKEN`, `WEBHOOK_SECRET`, `OWNER_CHAT_ID`) — лише параметри SAM з `NoEcho` і локальний `.env`.
- `samconfig.toml` після `sam deploy --guided` містить ці параметри відкритим текстом — він у `.gitignore`, не комітьте його.
- Особистий `plan.json` і бекапи `/export` теж у `.gitignore`. У репо лише `plan.example.json`.
- Webhook без правильного заголовка `X-Telegram-Bot-Api-Secret-Token` отримує 403. Оновлення не від власника ігноруються.
- Токен бота ніколи не потрапляє в логи: помилки Telegram логуються без URL.

## Розгортання

### 0. Підготовка
1. `@BotFather` → `/newbot` → токен.
2. Свій `chat_id` — наприклад, через `@userinfobot`.
3. AWS-акаунт, `aws configure` (регіон `eu-central-1`), AWS SAM CLI, Python 3.12.
4. `WEBHOOK_SECRET` — довгий випадковий рядок (лише `A-Z a-z 0-9 _ -`, ≥ 32 символи):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
5. Скопіюйте `.env.example` → `.env` і заповніть (потрібно лише для скриптів).

### 1. Локальна перевірка
```bash
pip install pytest tzdata
python -m pytest                       # логіка і хендлери з фейками, без AWS
python scripts/preview.py              # усі тексти бота на plan.example.json
python scripts/send_hello.py           # бот надсилає вам «hello»
```

### 2. Деплой
```bash
python scripts/deploy.py   # sam build + sam deploy, секрети з .env, samconfig.toml не потрібен
```
Альтернатива — `sam build && sam deploy --guided` (stack name: `planabot`, region: `eu-central-1`).

IAM-користувачу, який деплоїть, потрібні права на EventBridge Scheduler (`scheduler:CreateSchedule/GetSchedule/UpdateSchedule/DeleteSchedule` і `iam:PassRole` для ролей `planabot-*` з `iam:PassedToService = scheduler.amazonaws.com`), окрім звичних для SAM CloudFormation/Lambda/IAM/DynamoDB/S3.
На питання *«WebhookFunction Function Url has no authentication. Is this okay?»* відповідайте `y` — захист робить секретний заголовок.
У виводі будуть `FunctionUrl` і `WebhookUrl` (= `FunctionUrl` + `webhook`).

### 3. Webhook
```bash
python scripts/setup_webhook.py https://<id>.lambda-url.eu-central-1.on.aws/
```
Можна передати як `FunctionUrl`, так і `WebhookUrl` — скрипт сам допише `/webhook`. Він викликає `setWebhook` з `secret_token`, реєструє меню команд і показує `getWebhookInfo`.

### 4. Перевірка
- `/start` у Telegram відповідає.
- `/import`, потім надіслати свій `plan.json` документом.
- `/today` — задачі й звички, кнопки перемикаються в тому ж повідомленні.
- Нагадування: `sam remote invoke SchedulerFunction --stack-name planabot --event '{"kind":"late"}'`
  (`late` надсилає повідомлення лише якщо вчора пропуск і сьогодні порожньо; `morning` — завжди).
- Логи: `sam logs --stack-name planabot -n WebhookFunction --tail`.

## Нагадування (Europe/Kyiv)

| Коли | Що |
|---|---|
| 09:00 щодня | план дня з кнопками |
| 21:00 щодня | якщо день порожній — мінімум; завжди — питання про нотатку дня (наступне текстове повідомлення збережеться) |
| 23:00 щодня | 🚨 якщо вчора пропуск і сьогодні порожньо |
| Нд 20:00 | тижневий звіт + нотатки тижня |

Час змінюється в `template.yaml` (`ScheduleExpression`).

## Формат `plan.json`

Див. [plan.example.json](plan.example.json). `id` — до 40 символів `A-Z a-z 0-9 _ -`. `/import` замінює звички, задачі, цілі й мінімуми; історію днів не чіпає. Поле `rewards` у версії 1 ігнорується (знадобиться для магазину нагород у версії 2).
Сфери: `Інженер`, `Англійська`, `Тіло`, `Розум`, `Життя`. Горизонти: `Грудень`, `3 міс`, `6 міс`, `12 міс`.

Таблиця DynamoDB має `DeletionPolicy: Retain` і point-in-time recovery: дані переживуть `sam delete`.

## Далі: версія 2 (Mini App)

Після 1–2 тижнів роботи версії 1 — Telegram Mini App з дашбордом, XP, рівнями і нагородами. План, API і вимоги до безпеки (перевірка підпису `initData`) — у [SPEC.md, розділ 7](SPEC.md).
