"""
Главный файл для запуска системы бронирования переговорных комнат.
Запускает Telegram-бота и VK-бота в отдельных процессах.
"""

import asyncio
import logging
import sys
import subprocess

from config import LOG_LEVEL, LOG_FORMAT


vk_process = None


def setup_logging():
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


def start_vk_bot_subprocess():
    global vk_process
    python_executable = sys.executable
    vk_process = subprocess.Popen(
        [python_executable, "run_vk.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    logger = logging.getLogger(__name__)
    logger.info(f"VK-бот запущен в отдельном процессе (PID: {vk_process.pid})")

    def read_output():
        for line in vk_process.stdout:
            logging.getLogger("vk_bot").info(line.strip())

    import threading
    thread = threading.Thread(target=read_output, daemon=True)
    thread.start()
    return vk_process


def stop_vk_bot():
    global vk_process
    logger = logging.getLogger(__name__)
    if vk_process is not None and vk_process.poll() is None:
        logger.info("Остановка VK-бота...")
        vk_process.terminate()
        try:
            vk_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            vk_process.kill()
            vk_process.wait()
        logger.info("VK-бот остановлен")


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Запуск системы бронирования переговорных комнат")
    logger.info("=" * 60)

    start_vk_bot_subprocess()

    from tg_bot import start_telegram_bot

    try:
        await start_telegram_bot()
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения. Остановка системы...")
    except Exception as e:
        logger.error(f"Ошибка Telegram-бота: {e}", exc_info=True)
        raise
    finally:
        stop_vk_bot()
        logger.info("Система бронирования остановлена.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nСистема остановлена пользователем.")
        sys.exit(0)
