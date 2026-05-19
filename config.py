"""
Конфигурационный файл для системы бронирования переговорных комнат.
Содержит настройки ботов, Google Sheets и параметры бронирования.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройки Telegram бота
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Настройки VK бота
VK_BOT_TOKEN = os.getenv("VK_BOT_TOKEN", "")
VK_API_VERSION = "5.131"  # Версия VK API

# Настройки Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
GOOGLE_SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "")
GOOGLE_SPREADSHEET_URL = os.getenv("GOOGLE_SPREADSHEET_URL", "")

# Название листа для бронирований
BOOKINGS_SHEET_NAME = "bookings"

# Параметры бронирования
BOOKING_STEP_MINUTES = 30  # Шаг бронирования в минутах
MAX_BOOKING_HOURS = 3  # Максимальная длительность бронирования в часах
WORK_DAY_START = 9  # 9:00 - начало рабочего дня
WORK_DAY_END = 18  # 18:00 - окончание рабочего дня

# Настройки переговорных комнат
ROOMS = {
    "loft_living": {
        "id": "loft_living",
        "name": "Лофт-Гостиная",
        "description": "Уютная комната с диванами, креслами и журнальным столиком для неформальных встреч.",
        "capacity": "4-6 человек",
        "image_path": "images/coworking.jpg",
        "features": ["Диваны", "Кресла", "Журнальный столик", "Уютная атмосфера"]
    },
    "premium_boardroom": {
        "id": "premium_boardroom",
        "name": "Премиум-Бордрум",
        "description": "Массивный деревянный стол, кожаные кресла, панорамные окна. Для важных переговоров.",
        "capacity": "8-12 человек",
        "image_path": "images/big.jpg",
        "features": ["Массивный стол", "Кожаные кресла", "Панорамные окна", "Премиум интерьер"]
    },
    "glass_openspace": {
        "id": "glass_openspace",
        "name": "Стеклянный Опенспейс",
        "description": "Современная светлая переговорная со стеклянными стенами и длинным столом для командных спринтов.",
        "capacity": "6-10 человек",
        "image_path": "images/small.jpg",
        "features": ["Стеклянные стены", "Длинный стол", "Светлое пространство", "Современный дизайн"]
    }
}

# Пути к файлам
BASE_DIR = Path(__file__).parent
IMAGES_DIR = BASE_DIR / "images"

# Настройки логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
