"""
VK-бот обработчики сообщений.
Используются декораторы @labeler.message() для регистрации хэндлеров.
"""

import logging
import re
import time
import asyncio
from datetime import datetime, timedelta

from vkbottle import Keyboard, KeyboardButtonColor, Text
from vkbottle.bot import Message

from vk.loader import labeler
from vk.vk_bot import (
    is_admin,
    check_rate_limit,
    get_main_menu_keyboard,
    get_admin_menu_keyboard,
    get_view_bookings_keyboard,
    get_view_date_keyboard,
    get_rooms_keyboard,
    get_date_keyboard,
    get_time_keyboard,
    get_duration_keyboard,
    get_confirm_keyboard,
    get_cancel_booking_keyboard,
    get_user_data,
    set_user_data,
    update_user_data,
    get_user_name,
    format_bookings_list,
    BookingState,
    ROOMS,
    TIMEZONE,
    logger,
)
from data.database import db, BookingConflictError, ValidationError

print("✅ Хэндлеры загружены!")


# === RATE LIMITING ДЕКОРАТОР ===
def rate_limit():
    """Декоратор для проверки rate limiting перед обработкой сообщения."""
    def decorator(handler):
        async def wrapper(message: Message, **kwargs):
            if not check_rate_limit(message.from_id):
                await message.answer("⚠️ Пожалуйста, не спамьте. Подождите немного.")
                return
            return await handler(message, **kwargs)
        return wrapper
    return decorator


# === ОСНОВНЫЕ ХЭНДЛЕРЫ ===

@labeler.message(text=["/start", "Начать", "Меню", "меню", "◀️ Главное меню"])
@rate_limit()
async def cmd_start(message: Message):
    set_user_data(message.peer_id, {})
    try:
        from vk.vk_bot import bot
        await bot.state_dispenser.delete(message.peer_id)
    except KeyError:
        pass
    await message.answer(
        "👋 Добро пожаловать в систему бронирования переговорных комнат!\n\n"
        "Здесь вы можете:\n"
        "• 📅 Забронировать комнату для встречи\n"
        "• 📋 Просмотреть все бронирования\n"
        "• 📋 Управлять своими бронированиями\n\n"
        "Выберите действие:",
        keyboard=get_main_menu_keyboard(message.from_id)
    )


@labeler.message(text="Помощь")
@rate_limit()
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


@labeler.message(text="📅 Забронировать комнату")
@rate_limit()
async def process_book_room(message: Message):
    from vk.vk_bot import bot
    await bot.state_dispenser.set(message.peer_id, BookingState.SELECTING_ROOM)
    await message.answer(
        "🏢 Выберите переговорную комнату:",
        keyboard=get_rooms_keyboard()
    )


@labeler.message(text="📋 Просмотр броней")
@rate_limit()
async def process_view_bookings(message: Message):
    from vk.vk_bot import bot
    await bot.state_dispenser.set(message.peer_id, BookingState.VIEWING_BOOKINGS)
    await message.answer(
        "Выберите, за какой период вы хотите посмотреть бронирования:",
        keyboard=get_view_bookings_keyboard()
    )


@labeler.message(text="📅 Брони на сегодня")
@rate_limit()
async def process_today_bookings(message: Message):
    today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")
    bookings = await db.get_bookings_by_date(today_str)
    
    text = format_bookings_list(bookings, today_str)
    await message.answer(text, keyboard=get_view_bookings_keyboard())
    

@labeler.message(text="🔍 Выбрать конкретную дату")
@rate_limit()
async def process_select_date_for_view(message: Message):
    from vk.vk_bot import bot
    await bot.state_dispenser.set(message.peer_id, BookingState.VIEWING_DATE_SELECT)
    await message.answer(
        "Выберите дату для просмотра бронирований:",
        keyboard=get_view_date_keyboard()
    )


@labeler.message(state=BookingState.VIEWING_DATE_SELECT)
@rate_limit()
async def process_view_date_selection(message: Message):
    from vk.vk_bot import bot
    text = message.text
    peer_id = message.peer_id

    if "◀️ Назад" in text:
        await bot.state_dispenser.set(peer_id, BookingState.VIEWING_BOOKINGS)
        await message.answer(
            "Выберите, за какой период вы хотите посмотреть бронирования:",
            keyboard=get_view_bookings_keyboard()
        )
        return

    date_match = re.search(r'\d{2}\.\d{2}\.\d{4}', text)
    if not date_match:
        await message.answer("⚠️ Пожалуйста, выберите дату из списка:", keyboard=get_view_date_keyboard())
        return

    date_str = date_match.group()
    bookings = await db.get_bookings_by_date(date_str)
    
    text = format_bookings_list(bookings, date_str)
    await message.answer(text, keyboard=get_view_bookings_keyboard())
    await bot.state_dispenser.set(peer_id, BookingState.VIEWING_BOOKINGS)


@labeler.message(text="📋 Мои бронирования")
@rate_limit()
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
        
        start_time = str(booking.get("Время Начала", ""))
        end_time = str(booking.get("Время Конца", ""))
        if ":" not in start_time:
            start_time = f"{start_time}:00"
        if ":" not in end_time:
            end_time = f"{end_time}:00"
        
        text += (
            f"🆔 #{booking['ID брони']}\n"
            f"🏢 {room_name}\n"
            f"📅 {booking['Дата']}\n"
            f"🕐 {start_time} — {end_time}\n"
            f"📝 {booking['Цель']}\n"
            f"——————————————\n"
        )

    first_booking_id = bookings[0]["ID брони"]
    await message.answer(text, keyboard=get_cancel_booking_keyboard(first_booking_id))


@labeler.message(state=BookingState.SELECTING_ROOM)
@rate_limit()
async def process_room_selection(message: Message):
    from vk.vk_bot import bot
    text = message.text
    peer_id = message.peer_id

    if "◀️ Назад" in text:
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass
        await message.answer(
            "Главное меню. Выберите действие:",
            keyboard=get_main_menu_keyboard(message.from_id)
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
        from vk.vk_bot import bot
        await message.answer_photo(
            room_data["image_path"],
            caption=caption,
            keyboard=get_date_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        await message.answer(caption, keyboard=get_date_keyboard())

    from vk.vk_bot import bot
    await bot.state_dispenser.set(peer_id, BookingState.SELECTING_DATE)


@labeler.message(state=BookingState.SELECTING_DATE)
@rate_limit()
async def process_date_selection(message: Message):
    from vk.vk_bot import bot
    text = message.text
    peer_id = message.peer_id

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


@labeler.message(state=BookingState.SELECTING_START_TIME)
@rate_limit()
async def process_time_selection(message: Message):
    from vk.vk_bot import bot
    text = message.text
    peer_id = message.peer_id

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


@labeler.message(state=BookingState.SELECTING_DURATION)
@rate_limit()
async def process_duration_selection(message: Message):
    from vk.vk_bot import bot
    text = message.text
    peer_id = message.peer_id

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


@labeler.message(state=BookingState.ENTERING_PURPOSE)
@rate_limit()
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

    from vk.vk_bot import bot
    await bot.state_dispenser.set(peer_id, BookingState.CONFIRMING)
    await message.answer(summary, keyboard=get_confirm_keyboard())


@labeler.message(state=BookingState.CONFIRMING)
@rate_limit()
async def process_confirm(message: Message):
    from vk.vk_bot import bot
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
            keyboard=get_main_menu_keyboard(message.from_id)
        )
        return

    if "✅" not in text and "Подтвердить" not in text:
        await message.answer("⚠️ Нажмите '✅ Подтвердить' или '❌ Отменить':", keyboard=get_confirm_keyboard())
        return

    data = get_user_data(peer_id)

    try:
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
            keyboard=get_main_menu_keyboard(message.from_id)
        )

    except BookingConflictError as e:
        await message.answer(str(e), keyboard=get_main_menu_keyboard(message.from_id))
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
        await message.answer(f"⚠️ Ошибка: {str(e)}", keyboard=get_main_menu_keyboard(message.from_id))
    except Exception as e:
        logger.error(f"Ошибка создания бронирования: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.", keyboard=get_main_menu_keyboard(message.from_id))
        try:
            await bot.state_dispenser.delete(peer_id)
        except KeyError:
            pass


@labeler.message(func=lambda msg: msg.text and "Отменить бронь #" in msg.text)
@rate_limit()
async def process_cancel_booking_by_id(message: Message):
    """Обработчик отмены бронирования по ID из кнопки."""
    match = re.search(r"#(\d+)", message.text)
    if not match:
        await message.answer("⚠️ Не удалось определить номер бронирования.")
        return

    booking_id = int(match.group(1))
    user_id = str(message.from_id)

    try:
        success, already_cancelled = await db.cancel_booking(booking_id, user_id, "VK")
        if already_cancelled:
            await message.answer(
                f"ℹ️ Бронирование #{booking_id} уже было отменено ранее.",
                keyboard=get_main_menu_keyboard(message.from_id)
            )
        elif success:
            await message.answer(
                f"✅ Бронирование #{booking_id} успешно отменено!",
                keyboard=get_main_menu_keyboard(message.from_id)
            )
        else:
            await message.answer(
                f"❌ Не удалось найти или отменить бронирование #{booking_id}.\n"
                f"Возможно, оно уже прошло или было отменено.",
                keyboard=get_main_menu_keyboard(message.from_id)
            )
    except Exception as e:
        logger.error(f"Ошибка при отмене бронирования: {e}")
        await message.answer(
            f"⚠️ Произошла ошибка при отмене: {e}",
            keyboard=get_main_menu_keyboard(message.from_id)
        )


@labeler.message(text="Отменить бронь")
@rate_limit()
async def process_cancel_booking_help(message: Message):
    await message.answer(
        "Чтобы отменить бронирование, выберите его в разделе '📋 Мои бронирования'",
        keyboard=get_main_menu_keyboard(message.from_id)
    )


@labeler.message(func=lambda msg: msg.text and (msg.text.startswith("TGVK") and len(msg.text) == 8))
@rate_limit()
async def process_auth_code(message: Message):
    """Обработчик кодов авторизации для связки аккаунтов."""
    auth_code = message.text.strip()
    vk_id = str(message.from_id)
    
    try:
        success = await db.link_vk_account(vk_id, auth_code)
        
        if success:
            await message.answer(
                f"🎉 Аккаунты успешно связаны!\n\n"
                f"Теперь вам доступны все ваши бронирования из Telegram.\n"
                f"Вы можете использовать любого бота для управления всеми бронями.",
                keyboard=get_main_menu_keyboard(message.from_id)
            )
        else:
            await message.answer(
                f"❌ Неверный или устаревший код\n\n"
                f"Убедитесь, что:\n"
                f"• Код введён правильно (например: TGVK1234)\n"
                f"• Код не старше 10 минут\n\n"
                f"Попробуйте снова или получите новый код в Telegram-боте.",
                keyboard=get_main_menu_keyboard(message.from_id)
            )
    except Exception as e:
        logger.error(f"Ошибка при связке аккаунтов: {e}")
        await message.answer(
            f"⚠️ Произошла ошибка. Попробуйте позже.",
            keyboard=get_main_menu_keyboard(message.from_id)
        )


# === АДМИН-ПАНЕЛЬ ===

@labeler.message(text="👑 Админ-панель")
async def admin_panel(message: Message):
    """Главное меню администратора."""
    if not is_admin(message.from_id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        "👑 Панель администратора\n\n"
        "Выберите действие:",
        keyboard=get_admin_menu_keyboard()
    )


@labeler.message(text="📊 Статистика за сегодня")
async def admin_stats(message: Message):
    """Статистика бронирований за сегодня."""
    if not is_admin(message.from_id):
        await message.answer("⛔ У вас нет доступа.")
        return
    
    try:
        stats = await db.get_today_stats()
        
        text = (
            f"📊 Статистика за {stats['date']}\n\n"
            f"📋 Всего броней: {stats['total']}\n"
            f"✅ Активных: {stats['active']}\n"
            f"❌ Отменено: {stats['cancelled']}\n\n"
        )
        
        if stats['top_rooms']:
            text += "🏢 Топ комнат:\n"
            for room_id, count in stats['top_rooms']:
                room_name = ROOMS.get(room_id, {}).get('name', room_id)
                text += f"  • {room_name}: {count} броней\n"
        else:
            text += "🏢 Сегодня броней пока нет."
        
        await message.answer(text, keyboard=get_admin_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await message.answer(
            "⚠️ Ошибка при получении статистики.",
            keyboard=get_admin_menu_keyboard()
        )


@labeler.message(text="🚫 Принудительная отмена")
async def admin_force_cancel(message: Message):
    """Начало принудительной отмены брони."""
    from vk.vk_bot import bot
    if not is_admin(message.from_id):
        await message.answer("⛔ У вас нет доступа.")
        return
    
    await bot.state_dispenser.set(message.peer_id, BookingState.ADMIN_FORCE_CANCEL)
    await message.answer(
        "🚫 Принудительная отмена брони\n\n"
        "Введите ID брони, которую нужно отменить:\n"
        "(только число, например: 42)",
        keyboard=get_admin_menu_keyboard()
    )


@labeler.message(state=BookingState.ADMIN_FORCE_CANCEL)
async def process_admin_force_cancel(message: Message):
    """Обработка ID брони для принудительной отмены."""
    from vk.vk_bot import bot
    if not is_admin(message.from_id):
        await message.answer("⛔ У вас нет доступа.")
        await bot.state_dispenser.delete(message.peer_id)
        return
    
    text = message.text.strip()
    
    if not text.isdigit():
        await message.answer(
            "⚠️ Пожалуйста, введите только число (ID брони).",
            keyboard=get_admin_menu_keyboard()
        )
        return
    
    booking_id = int(text)
    
    try:
        success = await db.admin_cancel_booking(booking_id)
        
        if success:
            await message.answer(
                f"✅ Бронь #{booking_id} успешно отменена администратором.",
                keyboard=get_admin_menu_keyboard()
            )
        else:
            await message.answer(
                f"ℹ️ Бронь #{booking_id} не найдена или уже отменена.",
                keyboard=get_admin_menu_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка принудительной отмены: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при отмене брони.",
            keyboard=get_admin_menu_keyboard()
        )
    
    from vk.vk_bot import bot
    await bot.state_dispenser.delete(message.peer_id)


@labeler.message(text="📢 Объявление (Рассылка)")
async def admin_broadcast(message: Message):
    """Начало рассылки объявления."""
    from vk.vk_bot import bot
    if not is_admin(message.from_id):
        await message.answer("⛔ У вас нет доступа.")
        return
    
    await bot.state_dispenser.set(message.peer_id, BookingState.ADMIN_BROADCAST)
    await message.answer(
        "📢 Рассылка объявления\n\n"
        "Введите текст, который будет разослан ВСЕМ пользователям:\n"
        "(максимум 4096 символов)",
        keyboard=get_admin_menu_keyboard()
    )


@labeler.message(state=BookingState.ADMIN_BROADCAST)
async def process_admin_broadcast(message: Message):
    """Отправка рассылки всем пользователям."""
    from vk.vk_bot import bot
    if not is_admin(message.from_id):
        await message.answer("⛔ У вас нет доступа.")
        await bot.state_dispenser.delete(message.peer_id)
        return
    
    broadcast_text = message.text.strip()
    
    if len(broadcast_text) < 5:
        await message.answer(
            "⚠️ Текст слишком короткий. Минимум 5 символов.",
            keyboard=get_admin_menu_keyboard()
        )
        return
    
    if len(broadcast_text) > 4096:
        await message.answer(
            "⚠️ Текст слишком длинный. Максимум 4096 символов.",
            keyboard=get_admin_menu_keyboard()
        )
        return
    
    try:
        users = await db.get_all_unique_users()
        
        if not users:
            await message.answer(
                "ℹ️ В базе пока нет зарегистрированных пользователей для рассылки.",
                keyboard=get_admin_menu_keyboard()
            )
            await bot.state_dispenser.delete(message.peer_id)
            return
        
        sent_count = 0
        failed_count = 0
        
        for user in users:
            vk_id = user.get("vk_id")
            
            if vk_id:
                try:
                    from vk.vk_bot import bot
                    await bot.api.messages.send(
                        user_id=int(vk_id),
                        message=f"📢 Объявление\n\n{broadcast_text[:4000]}",
                        random_id=0
                    )
                    sent_count += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Ошибка рассылки в VK {vk_id}: {e}")
                    failed_count += 1
        
        await message.answer(
            f"✅ Рассылка завершена\n\n"
            f"📤 Отправлено: {sent_count}\n"
            f"❌ Ошибок: {failed_count}\n"
            f"👥 Всего пользователей: {len(users)}",
            keyboard=get_admin_menu_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при рассылке.",
            keyboard=get_admin_menu_keyboard()
        )
    
    from vk.vk_bot import bot
    await bot.state_dispenser.delete(message.peer_id)


# === CATCH-ALL DEBUG ХЭНДЛЕР ===
@labeler.message()
async def catch_all_messages(message: Message):
    """Перехватывает все сообщения для отладки."""
    logger.info(f"VK BOT ПОЛУЧИЛ СООБЩЕНИЕ! Текст: '{message.text}', от ID: {message.from_id}, peer_id: {message.peer_id}")
