"""
Тестовый скрипт для проверки подключения к Google Sheets.
Запускается для проверки работы базы данных.
"""

import asyncio
import sys
from database import db, BookingConflictError, ValidationError

async def test_connection():
    """Проверка подключения к Google Sheets."""
    print("=" * 50)
    print("Тест подключения к Google Sheets")
    print("=" * 50)
    
    try:
        # Подключаемся к базе
        await db.connect()
        print("✅ Подключение успешно!")
        
        # Проверяем наличие таблицы
        print(f"\n📊 Таблица ID: {db._spreadsheet.id}")
        print(f"📄 Лист: {db._bookings_sheet.title}")
        
        # Получаем все бронирования
        bookings = await db.get_all_bookings()
        print(f"\n📋 Всего бронирований: {len(bookings)}")
        
        if bookings:
            print("\nПоследние 5 бронирований:")
            for b in bookings[-5:]:
                print(f"  #{b.get('ID брони')} | {b.get('Переговорка')} | {b.get('Дата')} | {b.get('Время Начала')}")
        else:
            print("ℹ️ Бронирований пока нет")
        
        # Проверяем доступные слоты на сегодня
        from datetime import datetime
        today = datetime.now().strftime("%d.%m.%Y")
        slots = await db.get_available_slots(today, "loft_living")
        print(f"\n🕐 Свободные слоты на сегодня (Лофт-Гостиная): {len(slots)}")
        if slots[:3]:
            print(f"  Примеры: {slots[:3]}")
        
        print("\n" + "=" * 50)
        print("✅ Все тесты пройдены!")
        print("=" * 50)
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        print("\nВозможные причины:")
        print("1. Неверный ID таблицы в .env")
        print("2. Сервисный аккаунт не имеет доступа к таблице")
        print("3. Неверный путь к service_account.json")
        print("\nРешение:")
        print("1. Открой свою Google Таблицу")
        print("2. Нажми 'Поделиться' (Share)")
        print("3. Добавь email из service_account.json с правами Editor")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_connection())
    sys.exit(0 if result else 1)
