"""
VK-бот для системы бронирования переговорных комнат.
Реализован на vkbottle 4.x.
"""

import logging
import re
import time
import asyncio
from datetime import datetime, timedelta

from vkbottle import Keyboard, KeyboardButtonColor, BaseStateGroup, Text
from vkbottle.bot import Message

from vk.loader import bot, labeler, storage
from config import VK_BOT_TOKEN, ROOMS, TIMEZONE, VK_ADMIN_IDS
from data.database import db, BookingConflictError, ValidationError

logger = logging.getLogger(__name__)

# === RATE LIMITING ===
THROTTLE_INTERVAL = 1.0
_last_request_time: dict[int, float] = {}


def is_admin(user_id: int) -> bool:
    return user_id in VK_ADMIN_IDS


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    last_time = _last_request_time.get(user_id, 0)
    if now - last_time < THROTTLE_INTERVAL:
        logger.warning(f"Rate limit triggered for VK user {user_id}")
        return False
    _last_request_time[user_id] = now
    return True


def rate_limit():
    def decorator(handler):
        async def wrapper(message: Message, **kwargs):
            if not check_rate_limit(message.from_id):
                await message.answer("⚠️ Пожалуйста, не спамьте. Подождите немного.")
                return
            return await handler(message, **kwargs)
        return wrapper
    return decorator


class BookingState(BaseStateGroup):
    SELECTING_ROOM = 1
    SELECTING_DATE = 2
    SELECTING_START_TIME = 3
    SELECTING_DURATION = 4
    ENTERING_PURPOSE = 5
    CONFIRMING = 6
    VIEWING_BOOKINGS = 7
    VIEWING_DATE_SELECT = 8
    ADMIN_FORCE_CANCEL = 9
    ADMIN_BROADCAST = 10


def get_main_menu_keyboard(user_id: int = None):
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("📅 Забронировать комнату"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📋 Просмотр броней"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text("📋 Мои бронирования"), color=KeyboardButtonColor.SECONDARY)
    if user_id and is_admin(user_id):
        keyboard.row()
        keyboard.add(Text("👑 Админ-панель"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_admin_menu_keyboard():
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("📊 Статистика за сегодня"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🚫 Принудительная отмена"), color=KeyboardButtonColor.NEGATIVE)
    keyboard.row()
    keyboard.add(Text("📢 Объявление (Рассылка)"), color=KeyboardButtonColor.POSITIVE)
    keyboard.row()
    keyboard.add(Text("◀️ Главное меню"), color=KeyboardButtonColor.SECONDARY)
    return keyboard


def get_view_bookings_keyboard():
    keyboard = Keyboard(one_time=False)
    keyboard.add(Text("📅 Брони на сегодня"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🔍 Выбрать конкретную дату"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("◀️ Главное меню"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def get_view_date_keyboard():
    keyboard = Keyboard(one_time=False)
    today = datetime.now(TIMEZONE)
    for i in range(7):
        date_obj = today + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m.%Y")
        day_name = date_obj.strftime("%A")
        day_ru = {"Monday": "Пн", "Tuesday": "Вт", "Wednesday": "Ср",
                  "Thursday": "Чт", "Friday": "Пт", "Saturday": "Сб", "Sunday": "Вс"}.get(day_name, day_name)
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
    today = datetime.now(TIMEZONE)
    for i in range(7):
        date_obj = today + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m.%Y")
        day_name = date_obj.strftime("%A")
        day_ru = {"Monday": "Пн", "Tuesday": "Вт", "Wednesday": "Ср",
                  "Thursday": "Чт", "Friday": "Пт", "Saturday": "Сб", "Sunday": "Вс"}.get(day_name, day_name)
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
    durations = [("30 минут", 30), ("1 час", 60), ("1.5 часа", 90),
                 ("2 часа", 120), ("2.5 часа", 150), ("3 часа", 180)]
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


def get_user_data(peer_id):
    data = storage.get(f"user_{peer_id}")
    return data or {}


def set_user_data(peer_id, data):
    storage.set(f"user_{peer_id}", data)


def update_user_data(peer_id, **kwargs):
    data = get_user_data(peer_id)
    data.update(kwargs)
    set_user_data(peer_id, data)


async def get_user_name(user_id):
    try:
        user_info = await bot.api.users.get(user_ids=user_id)
        if user_info:
            return f"{user_info[0].first_name} {user_info[0].last_name}"
    except Exception as e:
        logger.error(f"Ошибка получения имени пользователя: {e}")
    return f"ID: {user_id}"


def format_bookings_list(bookings, date_str):
    if not bookings:
        return f"На {date_str} бронирований пока нет."
    text = f"📅 Бронирования на {date_str}:\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        username = booking.get("Имя", "—")
        start_time = str(booking.get("Время Начала", ""))
        end_time = str(booking.get("Время Конца", ""))
        if ":" not in start_time:
            start_time = f"{start_time}:00"
        if ":" not in end_time:
            end_time = f"{end_time}:00"
        text += f"• {start_time} — {end_time} | {room_name} ({username})\n"
    return text


from vk import handlers
