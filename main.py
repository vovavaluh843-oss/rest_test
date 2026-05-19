"""
Главный файл для запуска системы бронирования переговорных комнат.
Запускает Telegram-бота и VK-бота в отдельных процессах.
"""

import asyncio
import logging
import sys
import multiprocessing
from multiprocessing import Process

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


def run_vk_bot():
    """Запускает VK-бота в отдельном процессе."""
    import asyncio
    setup_logging()
    from vk_bot import start_vk_bot
    asyncio.run(start_vk_bot())


async def main():
    """Главная корутина. Запускает TG-бота в основном процессе."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Запуск системы бронирования переговорных комнат")
    logger.info("=" * 60)

    # Запускаем VK-бота в отдельном процессе
    vk_process = Process(target=run_vk_bot, name="VK-Bot-Process")
    vk_process.start()
    logger.info(f"VK-бот запущен в отдельном процессе (PID: {vk_process.pid})")

    # Запускаем Telegram-бота в основном процессе
    from tg_bot import start_telegram_bot

    try:
        await start_telegram_bot()
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения. Остановка системы...")
    except Exception as e:
        logger.error(f"Ошибка Telegram-бота: {e}", exc_info=True)
        raise
    finally:
        logger.info("Остановка VK-бота...")
        if vk_process.is_alive():
            vk_process.terminate()
            vk_process.join(timeout=5)
            if vk_process.is_alive():
                vk_process.kill()
        logger.info("Система бронирования остановлена.")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nСистема остановлена пользователем.")
        sys.exit(0)
