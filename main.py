"""
Главный файл для запуска системы бронирования переговорных комнат.

Стратегия запуска:
- vkbottle управляет event loop через свой loop_wrapper.
- Telegram-бот добавляется как задача в loop_wrapper VK-бота.
- Оба бота работают параллельно в одном event loop.
"""

import logging
import sys

from config import LOG_LEVEL, LOG_FORMAT


def setup_logging():
    """Настраивает логирование для всего приложения."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("booking_system.log", encoding="utf-8")
        ]
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("vkbottle").setLevel(logging.WARNING)
    logging.getLogger("gspread").setLevel(logging.WARNING)


def main():
    """Главная функция запуска. Синхронная — управление отдается loop_wrapper vkbottle."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Запуск системы бронирования переговорных комнат")
    logger.info("=" * 60)

    # Импортируем ботов
    # При импорте tg_bot регистрируются все обработчики
    from tg_bot import dp, bot as tg_bot
    from vk_bot import bot as vk_bot

    # Добавляем Telegram polling как задачу в loop_wrapper VK-бота.
    # Так оба бота работают в одном event loop под управлением vkbottle.
    logger.info("Добавление Telegram-бота в loop_wrapper VK-бота...")
    vk_bot.loop_wrapper.add_task(dp.start_polling(tg_bot))

    logger.info("Система успешно инициализирована! Запускаем VK и TG ботов...")

    # Запускаем VK-бота. Он добавит свою задачу polling в loop_wrapper
    # и вызовет loop_wrapper.run(), который запустит ОБЕ задачи параллельно.
    vk_bot.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nСистема остановлена пользователем.")
        sys.exit(0)
