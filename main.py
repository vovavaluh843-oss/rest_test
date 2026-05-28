import asyncio
import logging
import signal
import sys
from tg.tg_bot import dp, bot as tg_bot
from vk.vk_bot import bot as vk_bot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Глобальный флаг для graceful shutdown
shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    """Обработчик сигналов SIGINT/SIGTERM для корректного завершения."""
    logger.info(f"Получен сигнал {sig.name}, инициируем graceful shutdown...")
    shutdown_event.set()


async def start_telegram():
    """Запускает Telegram-бота через aiogram polling."""
    try:
        logger.info("Инициализация Telegram-бота...")
        await tg_bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram-бот успешно запущен в режиме Polling!")
        await dp.start_polling(tg_bot)
    except asyncio.CancelledError:
        logger.info("Telegram-бот получил сигнал остановки.")
        raise
    except Exception as e:
        logger.error(f"Критическая ошибка в работе Telegram-бота: {e}", exc_info=True)


async def start_vk():
    """Запускает VK-бота через стандартный vkbottle polling."""
    try:
        logger.info("Инициализация VK-бота...")
        logger.info("VK-бот успешно запущен в режиме LongPoll!")
        await vk_bot.run_polling()
    except asyncio.CancelledError:
        logger.info("VK-бот получил сигнал остановки.")
        raise
    except Exception as e:
        logger.error(f"Критическая ошибка в работе VK-бота: {e}", exc_info=True)


async def main():
    logger.info("============================================================")
    logger.info("ЗАПУСК КРОССПЛАТФОРМЕННОЙ СИСТЕМЫ БРОНИРОВАНИЯ")
    logger.info("============================================================")

    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Запускаем обе задачи параллельно
    tg_task = asyncio.create_task(start_telegram(), name="telegram_bot")
    vk_task = asyncio.create_task(start_vk(), name="vk_bot")

    # Ждем завершения любой из задач или сигнала shutdown
    done, pending = await asyncio.wait(
        [tg_task, vk_task, shutdown_event.wait()],
        return_when=asyncio.FIRST_COMPLETED
    )

    # Отменяем оставшиеся задачи
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Логируем результат завершившихся задач
    for task in done:
        if task.get_name() == "telegram_bot":
            logger.info("Telegram-бот остановлен.")
        elif task.get_name() == "vk_bot":
            logger.info("VK-бот остановлен.")

    logger.info("============================================================")
    logger.info("Система бронирования остановлена.")
    logger.info("============================================================")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("============================================================")
        logger.info("Система бронирования успешно остановлена пользователем.")
        logger.info("============================================================")
