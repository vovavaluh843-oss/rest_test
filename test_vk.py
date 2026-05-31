from vkbottle.bot import Bot, Message
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

VK_TOKEN = os.getenv("VK_BOT_TOKEN")

bot = Bot(token=VK_TOKEN)


@bot.on.message()
async def test_handler(message: Message):
    print(f"\n[!!!] УРА! ПОЛУЧЕНО СООБЩЕНИЕ ОТ ID {message.from_id}: {message.text}\n")
    await message.answer("✅ Бот жив и читает сообщения!")


if __name__ == "__main__":
    print("Запуск тестового VK-бота...")
    print(f"Токен загружен: {'Да' if VK_TOKEN else 'НЕТ ТОКЕНА!'}")
    bot.run_forever()
