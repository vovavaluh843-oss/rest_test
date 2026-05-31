"""Точка входа для запуска VK бота как модуля."""
from vk.vk_bot import bot

if __name__ == "__main__":
    bot.run_forever()
