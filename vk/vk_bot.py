"""
VK-бот для системы бронирования переговорных комнат.
Реализован на vkbottle 4.x.
"""

import logging
import re
from datetime import datetime, timedelta

from vkbottle.bot import Bot, Message
from vkbottle import Keyboard, KeyboardButtonColor, BaseStateGroup, CtxStorage, Text

from config import VK_BOT_TOKEN, ROOMS
from data.database import db, BookingConflictError, ValidationError

logger = logging.getLogger(__name__)

# === ИНИЦИАЛИЗАЦИЯ БОТА ===
bot = Bot(token=VK_BOT_TOKEN)
storage = CtxStorage()


class BookingState(BaseStateGroup):
    SELECTING_ROOM = 1
    SELECTING_DATE = 2
    SELECTING_START_TIME = 3
    SELECTING_DURATION = 4
    ENTERING_PURPOSE = 5
    CONFIRMING = 6
    VIEWING_BOOKINGS = 7  # Новое состояние для просмотра броней
    VIEWING_DATE_SELECT = 8  # Новое состояние для выбора даты просмотра


# === КЛАВИАТУРЫ ===

def get_main_menu_keyboard():
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("📅 Забронировать комнату"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📋 Просмотр броней"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text("📋 Мои бронирования"), color=KeyboardButtonColor.SECONDARY)
    return keyboard


def get_view_bookings_keyboard():
    """Клавиатура выбора периода просмотра броней."""
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("📅 Брони на сегодня"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🔍 Выбрать конкретную дату"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("◀️ Главное меню"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_view_date_keyboard():
    """Клавиатура для выбора даты просмотра броней."""
    keyboard = Keyboard(one_time=False)
    today = datetime.now()
    for i in range(7):
        date_obj = today + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m.%Y")
        day_name = date_obj.strftime("%A")
        day_ru = {
            "Monday": "Пн", "Tuesday": "Вт", "Wednesday": "Ср",
            "Thursday": "Чт", "Friday": "Пт", "Saturday": "Сб", "Sunday": "Вс"
        }.get(day_name, day_name)
        if i == 0:
            label = f"Сегодня ({date_str})"
        elif i == 1:
            label = f"Завтра ({date_str})"
        else:
            label = f"{day_ru} ({date_str})"
        keyboard.add(Text(label), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text("◀️ Назад к просмотру"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_rooms_keyboard():
    keyboard = Keyboard(one_time=False)
    for room_id, room_data in ROOMS.items():
        keyboard.add(Text(f"🏢 {room_data['name']}"), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text("◀️ Назад"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_date_keyboard():
    keyboard = Keyboard(one_time=False)
    today = datetime.now()
    for i in range(7):
        date_obj = today + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m.%Y")
        day_name = date_obj.strftime("%A")
        day_ru = {
            "Monday": "Пн", "Tuesday": "Вт", "Wednesday": "Ср",
            "Thursday": "Чт", "Friday": "Пт", "Saturday": "Сб", "Sunday": "Вс"
        }.get(day_name, day_name)
        if i == 0:
            label = f"Сегодня ({date_str})"
        elif i == 1:
            label = f"Завтра ({date_str})"
        else:
            label = f"{day_ru} ({date_str})"
        keyboard.add(Text(label), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text("◀️ Назад к комнатам"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_time_keyboard(available_slots):
    keyboard = Keyboard(one_time=False)
    for start, end in available_slots[:8]:
        keyboard.add(Text(f"🕐 {start}"), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text("◀️ Назад к дате"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_duration_keyboard():
    keyboard = Keyboard(one_time=False)
    durations = [
        ("30 минут", 30), ("1 час", 60), ("1.5 часа", 90),
        ("2 часа", 120), ("2.5 часа", 150), ("3 часа", 180),
    ]
    for label, minutes in durations:
        keyboard.add(Text(label), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text("◀️ Назад ко времени"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_confirm_keyboard():
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("✅ Подтвердить"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    keyboard.add(Text("❌ Отменить"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_cancel_booking_keyboard(booking_id):
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text(f"❌ Отменить бронь #{booking_id}"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.row()
    keyboard.add(Text("◀️ Главное меню"), color=KeyboardButtonColor.SECONDARY)
    return keyboard


# === ХРАНИЛИЩЕ ДАННЫХ ===

def get_user_data(peer_id):
    data = storage.get(f"user_{peer_id}")
    return data or {}


def set_user_data(peer_id, data):
    storage.set(f"user_{peer_id}", data)


def update_user_data(peer_id, **kwargs):
    data = get_user_data(peer_id)
    data.update(kwargs)
    set_user_data(peer_id, data)


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

async def get_user_name(user_id):
    """Получает имя пользователя через VK API."""
    try:
        user_info = await bot.api.users.get(user_ids=user_id)
        if user_info:
            return f"{user_info[0].first_name} {user_info[0].last_name}"
    except Exception as e:
        logger.error(f"Ошибка получения имени пользователя: {e}")
    return f"ID: {user_id}"


def format_bookings_list(bookings, date_str):
    """Формирует красивый список бронирований."""
    if not bookings:
        return f"На {date_str} бронирований пока нет."

    text = f"📅 Бронирования на {date_str}:\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        username = booking.get("Имя", "—")
        text += (
            f"• {booking['Время Начала']} — {booking['Время Конца']} | "
            f"{room_name} ({username})\n"
        )
    return text


# === ОБРАБОТЧИКИ ===

@bot.on.message(text=["/start", "Начать", "Меню", "меню", "◀️ Главное меню"])
async def cmd_start(message: Message):
    set_user_data(message.peer_id, {})
    try:
        await bot.state_dispenser.delete(message.peer_id)
    except KeyError:
        pass  # Стейт может не существовать
    await message.answer(
        "👋 Добро пожаловать в систему бронирования переговорных комнат!\n\n"
        "Здесь вы можете:\n"
        "• 📅 Забронировать комнату для встречи\n"
        "• 📋 Просмотреть все бронирования\n"
        "• 📋 Управлять своими бронированиями\n\n"
        "Выберите действие:",
        keyboard=get_main_menu_keyboard()
    )


@bot.on.message(text="Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📖 Помощь по системе бронирования\n\n"
        "Правила бронирования:\n"
        "• Бронирование доступно с 9:00 до 18:00\n"
        "• Шаг бронирования — 30 минут\n"
        "• Максимальная длительность — 3 часа\n"
        "• Нельзя бронировать на прошедшее время\n\n"
        "Комнаты:\n"
        "• Лофт-Гостиная (4-6 чел.)\n"
        "• Премиум-Бордрум (8-12 чел.)\n"
        "• Стеклянный Опенспейс (6-10 чел.)"
    )


@bot.on.message(text="📅 Забронировать комнату")
async def process_book_room(message: Message):
    await bot.state_dispenser.set(message.peer_id, BookingState.SELECTING_ROOM)
    await message.answer(
        "🏢 Выберите переговорную комнату:",
        keyboard=get_rooms_keyboard()
    )


@bot.on.message(text="📋 Просмотр броней")
async def process_view_bookings(message: Message):
    await bot.state_dispenser.set(message.peer_id, BookingState.VIEWING_BOOKINGS)
    await message.answer(
        "Выберите, за какой период вы хотите посмотреть бронирования:",
        keyboard=get_view_bookings_keyboard()
    )


@bot.on.message(text="📅 Брони на сегодня")
async def process_today_bookings(message: Message):
    today_str = datetime.now().strftime("%d.%m.%Y")
    bookings = await db.get_bookings_by_date(today_str)
    
    text = format_bookings_list(bookings, today_str)
    await message.answer(text, keyboard=get_view_bookings_keyboard())


@bot.on.message(text="🔍 Выбрать конкретную дату")
async def process_select_date_for_view(message: Message):
    await bot.state_dispenser.set(message.peer_id, BookingState.VIEWING_DATE_SELECT)
    await message.answer(
        "Выберите дату для просмотра бронирований:",
        keyboard=get_view_date_keyboard()
    )


@bot.on.message(state=BookingState.VIEWING_DATE_SELECT)
async def process_view_date_selection(message: Message):
    text = message.text
    peer_id = message.peer_id

    # Проверяем, что это команда назад
    if "◀️ Назад" in text:
        await bot.state_dispenser.set(peer_id, BookingState.VIEWING_BOOKINGS)
        await message.answer(
            "Выберите, за какой период вы хотите посмотреть бронирования:",
            keyboard=get_view_bookings_keyboard()
        )
        return

    # Извлекаем дату из текста
    date_match = re.search(r'\d{2}\.\d{2}\.\d{4}', text)
    if not date_match:
        await message.answer("⚠️ Пожалуйста, выберите дату из списка:", keyboard=get_view_date_keyboard())
        return

    date_str = date_match.group()
    bookings = await db.get_bookings_by_date(date_str)
    
    text = format_bookings_list(bookings, date_str)
    await message.answer(text, keyboard=get_view_bookings_keyboard())
    
    # Возвращаем в состояние выбора периода
    await bot.state_dispenser.set(peer_id, BookingState.VIEWING_BOOKINGS)


@bot.on.message(text="📋 Мои бронирования")
async def process_my_bookings(message: Message):
    user_id = str(message.peer_id)
    bookings = await db.get_user_bookings(user_id, "VK")

    if not bookings:
        keyboard = Keyboard(one_time=False)
        keyboard.add(Text("📅 Забронировать"), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("◀️ Главное меню"), color=KeyboardButtonColor.SECONDARY)
        await message.answer(
            "📋 У вас пока нет активных бронирований.\n\n"
            "Хотите забронировать комнату?",
            keyboard=keyboard
        )
        return

    text = "📋 Ваши активные бронирования:\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        text += (
            f"🆔 #{booking['ID брони']}\n"
            f"🏢 {room_name}\n"
            f"📅 {booking['Дата']}\n"
            f"🕐 {booking['Время Начала']} — {booking['Время Конца']}\n"
            f"📝 {booking['Цель']}\n"
            f"——————————————\n"
        )

    first_booking_id = bookings[0]["ID брони"]
    await message.answer(text, keyboard=get_cancel_booking_keyboard(first_booking_id))


@bot.on.message(state=BookingState.SELECTING_ROOM)
async def process_room_selection(message: Message):
    text = message.text
    peer_id = message.peer_id

    # Проверяем команду назад
    if "◀️ Назад" in text:
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass
        await message.answer(
            "Главное меню. Выберите действие:",
            keyboard=get_main_menu_keyboard()
        )
        return

    room_id = None
    for rid, rdata in ROOMS.items():
        if f"🏢 {rdata['name']}" in text or rdata['name'] in text:
            room_id = rid
            break

    if not room_id:
        await message.answer("⚠️ Пожалуйста, выберите комнату из списка:", keyboard=get_rooms_keyboard())
        return

    room_data = ROOMS[room_id]
    set_user_data(peer_id, {"room_id": room_id, "room_name": room_data["name"]})

    features_text = "\n".join([f"  ✓ {f}" for f in room_data["features"]])
    caption = (
        f"{room_data['name']}\n\n"
        f"{room_data['description']}\n\n"
        f"Вместимость: {room_data['capacity']}\n\n"
        f"Преимущества:\n{features_text}\n\n"
        f"Выберите дату бронирования:"
    )

    try:
        await message.answer_photo(
            room_data["image_path"],
            caption=caption,
            keyboard=get_date_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        await message.answer(caption, keyboard=get_date_keyboard())

    await bot.state_dispenser.set(peer_id, BookingState.SELECTING_DATE)


@bot.on.message(state=BookingState.SELECTING_DATE)
async def process_date_selection(message: Message):
    text = message.text
    peer_id = message.peer_id

    # Проверяем команду назад
    if "◀️ Назад" in text:
        await bot.state_dispenser.set(peer_id, BookingState.SELECTING_ROOM)
        await message.answer(
            "🏢 Выберите переговорную комнату:",
            keyboard=get_rooms_keyboard()
        )
        return

    date_match = re.search(r'\d{2}\.\d{2}\.\d{4}', text)
    if not date_match:
        await message.answer("⚠️ Пожалуйста, выберите дату из списка:", keyboard=get_date_keyboard())
        return

    date_str = date_match.group()
    update_user_data(peer_id, date_str=date_str)

    data = get_user_data(peer_id)
    room_id = data["room_id"]

    available_slots = await db.get_available_slots(date_str, room_id)

    if not available_slots:
        await message.answer(
            f"📅 На {date_str} все слоты заняты.\n\n"
            f"Выберите другую дату:",
            keyboard=get_date_keyboard()
        )
        return

    await bot.state_dispenser.set(peer_id, BookingState.SELECTING_START_TIME)
    await message.answer(
        f"📅 {date_str}\n\n"
        f"Выберите время начала встречи:",
        keyboard=get_time_keyboard(available_slots)
    )


@bot.on.message(state=BookingState.SELECTING_START_TIME)
async def process_time_selection(message: Message):
    text = message.text
    peer_id = message.peer_id

    # Проверяем команду назад
    if "◀️ Назад" in text:
        await bot.state_dispenser.set(peer_id, BookingState.SELECTING_DATE)
        data = get_user_data(peer_id)
        date_str = data.get("date_str", "")
        room_id = data.get("room_id", "")
        available_slots = await db.get_available_slots(date_str, room_id)
        await message.answer(
            f"📅 {date_str}\n\nВыберите дату:",
            keyboard=get_date_keyboard()
        )
        return

    time_match = re.search(r'(\d{2}:\d{2})', text)
    if not time_match:
        await message.answer("⚠️ Пожалуйста, выберите время из списка:", keyboard=get_time_keyboard([]))
        return

    start_time = time_match.group(1)
    update_user_data(peer_id, start_time=start_time)

    await bot.state_dispenser.set(peer_id, BookingState.SELECTING_DURATION)
    await message.answer(
        f"🕐 Начало: {start_time}\n\n"
        f"Выберите длительность встречи:",
        keyboard=get_duration_keyboard()
    )


@bot.on.message(state=BookingState.SELECTING_DURATION)
async def process_duration_selection(message: Message):
    text = message.text
    peer_id = message.peer_id

    # Проверяем команду назад
    if "◀️ Назад" in text:
        await bot.state_dispenser.set(peer_id, BookingState.SELECTING_START_TIME)
        data = get_user_data(peer_id)
        date_str = data.get("date_str", "")
        room_id = data.get("room_id", "")
        available_slots = await db.get_available_slots(date_str, room_id)
        await message.answer(
            f"📅 {date_str}\n\nВыберите время начала:",
            keyboard=get_time_keyboard(available_slots)
        )
        return

    duration_map = {
        "30 минут": 30, "1 час": 60, "1.5 часа": 90,
        "2 часа": 120, "2.5 часа": 150, "3 часа": 180
    }

    duration_minutes = None
    for label, mins in duration_map.items():
        if label in text:
            duration_minutes = mins
            break

    if duration_minutes is None:
        await message.answer("⚠️ Пожалуйста, выберите длительность из списка:", keyboard=get_duration_keyboard())
        return

    update_user_data(peer_id, duration_minutes=duration_minutes)

    data = get_user_data(peer_id)
    start_time = data["start_time"]
    date_str = data["date_str"]

    # Защита: если время пришло без минут, добавляем :00
    if start_time and ":" not in str(start_time):
        start_time = f"{start_time}:00"

    start_dt = datetime.strptime(f"{date_str} {start_time}", "%d.%m.%Y %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    end_time = end_dt.strftime("%H:%M")

    update_user_data(peer_id, end_time=end_time)

    await bot.state_dispenser.set(peer_id, BookingState.ENTERING_PURPOSE)
    await message.answer(
        f"⏱ Длительность: {duration_minutes} мин.\n"
        f"🕐 {start_time} — {end_time}\n\n"
        f"Введите цель встречи (краткое описание):"
    )


@bot.on.message(state=BookingState.ENTERING_PURPOSE)
async def process_purpose(message: Message):
    peer_id = message.peer_id
    purpose = message.text.strip()

    if len(purpose) < 2:
        await message.answer("⚠️ Описание слишком короткое. Введите более подробную цель:")
        return

    if len(purpose) > 200:
        await message.answer("⚠️ Описание слишком длинное (макс. 200 символов). Введите кратче:")
        return

    update_user_data(peer_id, purpose=purpose)
    data = get_user_data(peer_id)

    summary = (
        f"📋 Проверьте данные бронирования:\n\n"
        f"🏢 Комната: {data['room_name']}\n"
        f"📅 Дата: {data['date_str']}\n"
        f"🕐 Время: {data['start_time']} — {data['end_time']}\n"
        f"📝 Цель: {purpose}\n\n"
        f"Подтвердите бронирование:"
    )

    await bot.state_dispenser.set(peer_id, BookingState.CONFIRMING)
    await message.answer(summary, keyboard=get_confirm_keyboard())


@bot.on.message(state=BookingState.CONFIRMING)
async def process_confirm(message: Message):
    peer_id = message.peer_id
    text = message.text

    if "❌" in text or "Отменить" in text:
        set_user_data(peer_id, {})
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass
        await message.answer(
            "❌ Бронирование отменено.\n\n"
            "Выберите действие:",
            keyboard=get_main_menu_keyboard()
        )
        return

    if "✅" not in text and "Подтвердить" not in text:
        await message.answer("⚠️ Нажмите '✅ Подтвердить' или '❌ Отменить':", keyboard=get_confirm_keyboard())
        return

    data = get_user_data(peer_id)

    try:
        # Получаем имя пользователя через VK API
        user_name = await get_user_name(message.from_id)

        booking_id = await db.create_booking(
            user_name=user_name,
            platform="VK",
            user_id=str(message.from_id),
            room_id=data["room_id"],
            date_str=data["date_str"],
            start_time_str=data["start_time"],
            end_time_str=data["end_time"],
            purpose=data["purpose"]
        )

        set_user_data(peer_id, {})
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass
        await message.answer(
            f"✅ Бронирование успешно создано!\n\n"
            f"🏢 Комната: {data['room_name']}\n"
            f"📅 Дата: {data['date_str']}\n"
            f"🕐 Время: {data['start_time']} — {data['end_time']}\n"
            f"🆔 Номер брони: #{booking_id}\n\n"
            f"Ждем вас на встрече!",
            keyboard=get_main_menu_keyboard()
        )

    except BookingConflictError as e:
        await message.answer(str(e), keyboard=get_main_menu_keyboard())
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass
    except ValidationError as e:
        set_user_data(peer_id, {})
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass
        await message.answer(f"⚠️ Ошибка: {str(e)}", keyboard=get_main_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка создания бронирования: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.", keyboard=get_main_menu_keyboard())
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass


@bot.on.message(func=lambda msg: msg.text and "Отменить бронь #" in msg.text)
async def process_cancel_booking_by_id(message: Message):
    """Обработчик отмены бронирования по ID из кнопки."""
    # Извлекаем ID брони из текста сообщения
    match = re.search(r"#(\d+)", message.text)
    if not match:
        await message.answer("⚠️ Не удалось определить номер бронирования.")
        return

    booking_id = int(match.group(1))
    user_id = str(message.from_id)

    try:
        success = await db.cancel_booking(booking_id, user_id, "VK")
        if success:
            await message.answer(
                f"✅ Бронирование #{booking_id} успешно отменено!",
                keyboard=get_main_menu_keyboard()
            )
        else:
            await message.answer(
                f"❌ Не удалось найти или отменить бронирование #{booking_id}.\n"
                f"Возможно, оно уже прошло или было отменено.",
                keyboard=get_main_menu_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка при отмене бронирования: {e}")
        await message.answer(
            f"⚠️ Произошла ошибка при отмене: {e}",
            keyboard=get_main_menu_keyboard()
        )


@bot.on.message(text="Отменить бронь")
async def process_cancel_booking_help(message: Message):
    await message.answer(
        "Чтобы отменить бронирование, выберите его в разделе '📋 Мои бронирования'",
        keyboard=get_main_menu_keyboard()
    )
