"""
Главный файл для запуска системы бронирования переговорных комнат.
Запускает Telegram-бота и VK-бота параллельно в одном event loop.
"""

import asyncio
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


async def main():
    """Главная корутина. Запускает TG и VK ботов параллельно."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Запуск системы бронирования переговорных комнат")
    logger.info("=" * 60)

    # Импортируем ботов
    from tg_bot import dp, bot as tg_bot
    from vk_bot import start_vk_bot

    # Создаем задачу для polling VK-бота внутри текущего loop
    vk_task = asyncio.create_task(start_vk_bot())

    # Запускаем polling Telegram-бота (drop_pending пропускает старые спам-апдейты)
    await tg_bot.delete_webhook(drop_pending_updates=True)
    tg_task = asyncio.create_task(dp.start_polling(tg_bot))

    logger.info("Система успешно запущена: TG и VK боты работают!")

    # Ждем завершения обеих задач (если одна упадет — другая тоже завершится)
    try:
        await asyncio.gather(vk_task, tg_task)
    except asyncio.CancelledError:
        logger.info("Получен сигнал завершения...")
    except Exception as e:
        logger.error(f"Ошибка в работе ботов: {e}", exc_info=True)
        raise
    finally:
        logger.info("Система бронирования остановлена.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nСистема остановлена пользователем.")
        sys.exit(0)
