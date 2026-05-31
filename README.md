# 🏢 Кроссплатформенная система бронирования переговорных комнат

Бот для бронирования переговорных комнат, работающий одновременно в **Telegram** и **ВКонтакте**. Google Sheets используется как база данных — любой сотрудник может открыть таблицу и увидеть расписание.

## Возможности

### Для пользователей
- 🏢 Три переговорные комнаты с фотографиями и описанием
- 📅 Бронирование на 7 дней вперёд (выбор даты, времени, длительности)
- 🕐 Шаг 30 минут, максимум 3 часа, рабочие часы 9:00–18:00
- ✅ Мгновенное подтверждение — бронь создаётся сразу
- 📋 «Мои бронирования» — список с кнопкой отмены
- 🔗 Связка Telegram ↔ VK — забронировал в одном месте, управляешь в другом
- ⏰ Напоминания за 30 минут до начала

### Для администраторов
- 👑 Админ-панель (доступна только по ID)
- 📊 Статистика за сегодня
- 🚫 Принудительная отмена любой брони
- 📢 Массовая рассылка объявлений

---

## Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Telegram-бот | aiogram 3.x, FSM, Inline/Reply клавиатуры |
| VK-бот | vkbottle 4.x, FSM, Reply клавиатуры |
| База данных | Google Sheets (gspread + oauth2client) |
| Асинхронность | asyncio, asyncio.Lock (защита от race condition) |
| Логирование | RotatingFileHandler (5MB, 3 бэкапа) |
| Конфигурация | python-dotenv (.env) |

---

## Архитектура

```
┌─────────────────┐     ┌─────────────────┐
│  Telegram Bot   │     │    VK Bot       │
│   (aiogram 3.x) │     │  (vkbottle 4)   │
│  FSM + Middleware│     │  FSM + Rate Limit│
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
         ┌───────────▼───────────┐
         │  Единая бизнес-логика  │
         │  • asyncio.Lock        │
         │  • Валидация времени   │
         │  • Экранирование      │
         │  • Soft Delete         │
         └───────────┬───────────┘
                     │
           ┌─────────▼──────────┐
           │   Google Sheets     │
           │  • bookings         │
           │  • users_auth       │
           └─────────────────────┘
```

**Почему VK-бот запускается отдельным процессом?**  
`vkbottle.Bot.run_polling()` внутри вызывает `loop.run_until_complete()`, что конфликтует с уже запущенным asyncio event loop от aiogram. Решение — `subprocess.Popen` для VK и `asyncio.run` для TG в главном процессе.

---

## Структура проекта

```
booking-system/
├── main.py                 # Точка входа: TG polling + VK subprocess + reminder
├── config.py               # Конфигурация: токены, timezone, комнаты, админы
├── requirements.txt         # Зависимости Python
├── run.sh                   # Скрипт запуска с проверками
├── .env.example             # Шаблон переменных окружения
│
├── data/
│   ├── __init__.py
│   ├── database.py          # Работа с Google Sheets + бизнес-логика
│   └── service_account.json # Ключ Google API (не в git!)
│
├── tg/
│   └── tg_bot.py            # Telegram-бот (aiogram 3.x, FSM, inline-клавиатуры)
│
├── vk/
│   ├── __init__.py
│   ├── __main__.py           # Точка входа для python -m vk
│   └── vk_bot.py            # VK-бот (vkbottle 4.x, FSM, reply-клавиатуры)
│
├── images/                   # Фотографии переговорных
│   ├── coworking.jpg
│   ├── big.jpg
│   └── small.jpg
│
└── logs/                     # Логи с ротацией (создаётся автоматически)
    └── bot.log
```

---

## Установка и запуск

### Быстрый старт

```bash
# 1. Клонируем репозиторий
git clone <repository-url>
cd booking-system

# 2. Запускаем скрипт (проверит всё автоматически)
chmod +x run.sh
./run.sh
```

Скрипт `run.sh` автоматически:
- Создаст venv, если его нет
- Установит зависимости из requirements.txt
- Проверит наличие .env и обязательных переменных
- Проверит наличие service_account.json
- Запустит ботов с логированием

### Ручная установка

```bash
# 1. Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate      # Linux/macOS
# venv\Scripts\activate       # Windows

# 2. Устанавливаем зависимости
pip install -r requirements.txt

# 3. Настраиваем переменные окружения
cp .env.example .env
nano .env                      # Заполните токены

# 4. Проверяем подключение к Google Sheets
python3 test_db.py

# 5. Запускаем
python3 main.py
```

---

## Настройка

### Переменные окружения (.env)

```env
# Telegram — получите у @BotFather
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# VK — получите в настройках сообщества → API → Токен сообщества
VK_BOT_TOKEN=vk1.a.abc123def456...

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE=data/service_account.json
GOOGLE_SPREADSHEET_ID=1A2B3C4D5E6F7G8H9I0J
GOOGLE_SPREADSHEET_URL=https://docs.google.com/spreadsheets/d/...

# Логирование (опционально)
LOG_LEVEL=INFO
TIMEZONE=Europe/Moscow
```

### Создание Google Service Account

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект → Включите **Google Sheets API** и **Google Drive API**
3. IAM → Service Accounts → Создайте аккаунт → Создайте ключ (JSON)
4. Скачайте JSON-ключ → переименуйте в `service_account.json` → положите в `data/`
5. Создайте Google Таблицу → Поделиться → Добавьте email сервисного аккаунта с правами **Editor**
6. Скопируйте ID таблицы из URL в `GOOGLE_SPREADSHEET_ID`

### Настройка администраторов

В `config.py` укажите свои ID:

```python
TG_ADMIN_IDS = [123456789]   # Ваш Telegram ID (узнать у @userinfobot)
VK_ADMIN_IDS = [987654321]   # Ваш VK ID
```

### Добавление фотографий комнат

Положите изображения в папку `images/`:

| Файл | Комната |
|------|---------|
| `coworking.jpg` | Лофт-Гостиная |
| `big.jpg` | Премиум-Бордрум |
| `small.jpg` | Стеклянный Опенспейс |

---

## Структура Google Sheets

### Лист `bookings`

| A | B | C | D | E | F | G | H | I | J | K |
|---|---|---|---|---|---|---|---|---|---|---|
| ID брони | Имя | Платформа | ID пользователя | Переговорка | Дата | Время Начала | Время Конца | Цель | Статус | Уведомление |
| 1 | Иван | TG | 950069853 | loft_living | 15.06.2024 | 14:30 | 16:00 | Созвон | Активно | Нет |

### Лист `users_auth`

| A | B | C | D | E |
|---|---|---|---|---|
| telegram_id | vk_id | name | auth_code | code_expires |
| 950069853 | 445181972 | Иван | TGVK4823 | 15.06.2024 14:30 |

---

## Безопасность

| Аспект | Реализация |
|--------|-----------|
| Race condition | `asyncio.Lock` для каждой комнаты + двойная проверка слота |
| Формульные инъекции | `sanitize_input()` фильтрует `= + - @ \t \r \n` |
| Rate limiting | 1 секунда между запросами (TG middleware + VK декоратор) |
| Soft Delete | Статус «Отменено» вместо удаления строки |
| Логирование | RotatingFileHandler 5MB + 3 бэкапа + stdout |
| Graceful shutdown | Обработка SIGINT/SIGTERM, корректная отмена задач |
| Токены | Хранятся в .env (не в git), service_account.json в .gitignore |
| Валидация | Проверка даты, времени, длительности, рабочих часов |

---

## Связка аккаунтов (Telegram ↔ VK)

1. Пользователь нажимает «🔗 Привязать ВКонтакте» в Telegram
2. Бот генерирует одноразовый код (`TGVK4823`), действительный 10 минут
3. Пользователь отправляет код в VK-бот
4. VK-бот записывает `vk_id` в строку с этим кодом
5. Брони видны в обоих мессенджерах

---

## Устранение неполадок

| Проблема | Решение |
|-----------|---------|
| `Service account not found` | Проверьте путь к `data/service_account.json` |
| `Spreadsheet not found` | Проверьте `GOOGLE_SPREADSHEET_ID` и права доступа |
| VK-бот не отвечает | Проверьте токен, настройки Long Poll API в группе VK |
| TG-бот не отвечает | Проверьте токен у @BotFather, удалите webhook |
| Напоминания не приходят | Проверьте колонку K «Уведомление» в таблице |
| Админ-панель не видна | Проверьте `TG_ADMIN_IDS` / `VK_ADMIN_IDS` в config.py |

---

## Лицензия

Внутренний проект. Все права защищены.
