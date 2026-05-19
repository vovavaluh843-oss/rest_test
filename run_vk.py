"""
Отдельный скрипт для запуска VK-бота.
"""

import logging
from config import LOG_LEVEL, LOG_FORMAT
from vk_bot import start_vk_bot

if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler()]
    )
    logger = logging.getLogger("vk_runner")
    logger.info("Запуск VK-бота...")
    start_vk_bot()
