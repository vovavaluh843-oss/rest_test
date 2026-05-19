import asyncio
import logging
import sys
from tg_bot import dp, bot as tg_bot
from vk_bot import bot as vk_bot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def start_telegram():
    """Запускает Telegram-бота через aiogram polling."""
    try:
        logger.info("Инициализация Telegram-бота...")
        await tg_bot.delete_webhook(drop_pending=True)
        logger.info("Telegram-бот успешно запущен в режиме Polling!")
        await dp.start_polling(tg_bot)
    except Exception as e:
        logger.error(f"Критическая ошибка в работе Telegram-бота: {e}", exc_info=True)


async def start_vk():
    """
    Запускает VK-бота через асинхронный polling без loop_wrapper.run().
    Используем polling.listen() напрямую, как в исходном коде vkbottle.
    """
    try:
        logger.info("Инициализация VK-бота...")
        polling = vk_bot.polling
        logger.info(f"VK-бот успешно запущен в режиме LongPoll! (API: {polling.api})")

        async for event in polling.listen():
            logger.debug("Получено VK событие: %r", event)
            for update in event.get("updates", []):
                # Маршрутизируем событие через router vkbottle
                asyncio.create_task(vk_bot.router.route(update, polling.api))

    except Exception as e:
        logger.error(f"Критическая ошибка в работе VK-бота: {e}", exc_info=True)


async def main():
    logger.info("============================================================")
    logger.info("ЗАПУСК КРОССПЛАТФОРМЕННОЙ СИСТЕМЫ БРОНИРОВАНИЯ")
    logger.info("============================================================")
    # Запускаем обе задачи параллельно в одном общем Event Loop
    await asyncio.gather(
        start_telegram(),
        start_vk()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("============================================================")
        logger.info("Система бронирования успешно остановлена пользователем.")
        logger.info("============================================================")
