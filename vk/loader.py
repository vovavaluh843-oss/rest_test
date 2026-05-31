"""
VK-бот инициализация.
Создаёт объект бота и labeler для регистрации хэндлеров.
Разделён в отдельный модуль для предотвращения циклических импортов.
"""

from vkbottle.bot import Bot
from vkbottle import CtxStorage

from config import VK_BOT_TOKEN

print("Создаём объект бота...")
# Создаём объект бота
bot = Bot(token=VK_BOT_TOKEN)

# Создаём labeler для регистрации хэндлеров
labeler = bot.labeler

# Создаём хранилище состояний
storage = CtxStorage()

print("✅ vk/loader.py загрузился успешно!")


def get_bot():
    """Возвращает объект бота."""
    return bot


def get_labeler():
    """Возвращает labeler для регистрации хэндлеров."""
    return labeler


def get_storage():
    """Возвращает хранилище состояний."""
    return storage
