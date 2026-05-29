import asyncio
import logging
import logging.handlers
import os
import signal
import sys
from datetime import datetime, timedelta
from tg.tg_bot import dp, bot as tg_bot
from vk.vk_bot import bot as vk_bot
from data.database import db
from config import ROOMS, TIMEZONE

logger = logging.getLogger(__name__)
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
formatter = logging.Formatter(LOG_FORMAT)

# Handler: консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

# Handler: файл с ротацией (5MB, 3 backup)
file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOGS_DIR, "bot.log"),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding="utf-8"
)
file_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[console_handler, file_handler]
)
logger = logging.getLogger(__name__)

# Глобальный флаг для graceful shutdown
shutdown_event = asyncio.Event()


async def send_reminder(booking, tg_bot, vk_bot):
    """Отправляет напоминание пользователю через связанные платформы."""
    try:
        user_id = str(booking.get("ID пользователя", ""))
        platform = booking.get("Платформа", "")
        room_id = booking.get("Переговорка", "")
        date_str = booking.get("Дата", "")
        start_time = booking.get("Время Начала", "")
        end_time = booking.get("Время Конца", "")
        booking_id = booking.get("ID брони")
        
        room_name = ROOMS.get(room_id, {}).get("name", room_id)
        
        # Текст уведомления
        message = f"⏰ Напоминание: У вас забронирована переговорка '{room_name}' на сегодня с {start_time} до {end_time}. Ждем вас!"
        
        # Проверяем связанные аккаунты
        linked_ids = await db.get_linked_user_ids(user_id, platform)
        
        sent_tg = False
        sent_vk = False
        
        # Отправляем в Telegram
        if "tg_id" in [k for k in linked_ids if k.startswith("tg_id")]:
            # Проверяем, есть ли telegram_id
            try:
                for link_id in linked_ids:
                    if not link_id.startswith("tg_") and len(link_id) > 5:
                        # Это может быть telegram_id
                        await tg_bot.send_message(
                            chat_id=int(link_id),
                            text=message
                        )
                        sent_tg = True
                        logger.info(f"Напоминание отправлено в TG для брони #{booking_id}")
                        break
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания в TG: {e}")
        
        # Отправляем в VK
        try:
            await vk_bot.api.messages.send(
                user_id=int(user_id),
                message=message,
                random_id=0
            )
            sent_vk = True
            logger.info(f"Напоминание отправлено в VK для брони #{booking_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания в VK: {e}")
        
        # Если не привязано никуда, отправляем на платформу создания
        if not sent_tg and not sent_vk:
            if platform == "TG":
                try:
                    await tg_bot.send_message(
                        chat_id=int(user_id),
                        text=message
                    )
                    logger.info(f"Напоминание отправлено в TG (без связки) для брони #{booking_id}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в TG: {e}")
            elif platform == "VK":
                try:
                    await vk_bot.api.messages.send(
                        user_id=int(user_id),
                        message=message,
                        random_id=0
                    )
                    logger.info(f"Напоминание отправлено в VK (без связки) для брони #{booking_id}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в VK: {e}")
        
        # Помечаем как отправленное
        await db.mark_reminder_sent(booking_id)
        
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания: {e}")


async def reminder_scheduler():
    """
    Фоновая задача для отправки напоминаний о бронированиях.
    Проверяет каждую минуту, есть ли брони через 30 минут.
    """
    logger.info("✅ Reminder scheduler запущен")
    
    while not shutdown_event.is_set():
        try:
            # Получаем брони, требующие напоминания
            bookings_to_remind = await db.get_bookings_needing_reminders(reminder_minutes=30)
            
            if bookings_to_remind:
                logger.info(f"Найдено {len(bookings_to_remind)} броней для напоминания")
                
                for booking in bookings_to_remind:
                    await send_reminder(booking, tg_bot, vk_bot)
                    await asyncio.sleep(1)  # Небольшая задержка между отправками
            
            # Ждем минуту перед следующей проверкой
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Ошибка в reminder scheduler: {e}")
            await asyncio.sleep(60)


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

    # Запускаем обе задачи параллельно + reminder scheduler
    tg_task = asyncio.create_task(start_telegram(), name="telegram_bot")
    vk_task = asyncio.create_task(start_vk(), name="vk_bot")
    reminder_task = asyncio.create_task(reminder_scheduler(), name="reminder_scheduler")

    # Ждем завершения любой из задач или сигнала shutdown
    done, pending = await asyncio.wait(
        [tg_task, vk_task, reminder_task, shutdown_event.wait()],
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
        elif task.get_name() == "reminder_scheduler":
            logger.info("Reminder scheduler остановлен.")

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
