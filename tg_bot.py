"""
Telegram-бот для системы бронирования переговорных комнат.
Реализован на aiogram 3.x с использованием FSM.
"""

import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import TELEGRAM_BOT_TOKEN, ROOMS
from database import db, BookingConflictError, ValidationError

logger = logging.getLogger(__name__)

# Инициализация бота с HTML-разметкой
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()


class BookingStates(StatesGroup):
    selecting_room = State()
    selecting_date = State()
    selecting_start_time = State()
    selecting_duration = State()
    entering_purpose = State()
    confirming = State()
    viewing_bookings_date = State()  # Состояние для просмотра броней на дату


# === КЛАВИАТУРЫ ===

def get_main_reply_keyboard():
    """Reply-клавиатура главного меню."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Забронировать комнату")],
            [KeyboardButton(text="📋 Брони на сегодня")],
            [KeyboardButton(text="📅 Брони на дату")],
            [KeyboardButton(text="📋 Мои бронирования")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_main_menu_inline_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📅 Забронировать комнату", callback_data="book_room")],
        [InlineKeyboardButton(text="📋 Брони на сегодня", callback_data="today_bookings")],
        [InlineKeyboardButton(text="📅 Брони на дату", callback_data="view_date_menu")],
        [InlineKeyboardButton(text="📋 Мои бронирования", callback_data="my_bookings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_view_date_keyboard():
    """Клавиатура для выбора даты просмотра броней."""
    today = datetime.now()
    buttons = []
    for i in range(7):
        date_obj = today + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m.%Y")
        day_name = date_obj.strftime("%A").replace(
            "Monday", "Пн").replace("Tuesday", "Вт").replace(
            "Wednesday", "Ср").replace("Thursday", "Чт").replace(
            "Friday", "Пт").replace("Saturday", "Сб").replace("Sunday", "Вс")
        if i == 0:
            label = f"📅 Сегодня ({date_str})"
        elif i == 1:
            label = f"📅 Завтра ({date_str})"
        else:
            label = f"📅 {day_name} ({date_str})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"view_date:{date_str}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_rooms_keyboard():
    buttons = []
    for room_id, room_data in ROOMS.items():
        buttons.append([InlineKeyboardButton(
            text=f"🏢 {room_data['name']}",
            callback_data=f"room:{room_id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_date_keyboard():
    today = datetime.now()
    buttons = []
    for i in range(7):
        date_obj = today + timedelta(days=i)
        date_str = date_obj.strftime("%d.%m.%Y")
        day_name = date_obj.strftime("%A").replace(
            "Monday", "Пн").replace("Tuesday", "Вт").replace(
            "Wednesday", "Ср").replace("Thursday", "Чт").replace(
            "Friday", "Пт").replace("Saturday", "Сб").replace("Sunday", "Вс")
        if i == 0:
            label = f"📅 Сегодня ({date_str})"
        elif i == 1:
            label = f"📅 Завтра ({date_str})"
        else:
            label = f"📅 {day_name} ({date_str})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"date:{date_str}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад к комнатам", callback_data="book_room")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_time_keyboard(available_slots, date_str):
    buttons = []
    row = []
    for start, end in available_slots:
        row.append(InlineKeyboardButton(text=f"🕐 {start}", callback_data=f"time:{start}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад к дате", callback_data="back_to_date")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_duration_keyboard(start_time):
    buttons = []
    durations = [
        ("30 минут", 30), ("1 час", 60), ("1.5 часа", 90),
        ("2 часа", 120), ("2.5 часа", 150), ("3 часа", 180),
    ]
    row = []
    for label, minutes in durations:
        row.append(InlineKeyboardButton(text=label, callback_data=f"duration:{minutes}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад ко времени", callback_data="back_to_time")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_keyboard():
    buttons = [[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_booking")
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_booking_keyboard(booking_id):
    buttons = [[InlineKeyboardButton(text="❌ Отменить бронь", callback_data=f"cancel:{booking_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === ОБРАБОТЧИКИ КОМАНД ===

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в систему бронирования переговорных комнат!\n\n"
        "Здесь вы можете:\n"
        "• 📅 Забронировать комнату для встречи\n"
        "• 📋 Посмотреть брони на сегодня\n"
        "• 📋 Управлять своими бронированиями\n\n"
        "Выберите действие:",
        reply_markup=get_main_reply_keyboard()
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Помощь по системе бронирования</b>\n\n"
        "<b>Доступные команды:</b>\n"
        "/start — Главное меню\n"
        "/help — Эта справка\n\n"
        "<b>Правила бронирования:</b>\n"
        "• Бронирование доступно с 9:00 до 18:00\n"
        "• Шаг бронирования — 30 минут\n"
        "• Максимальная длительность — 3 часа\n"
        "• Нельзя бронировать на прошедшее время\n\n"
        "<b>Комнаты:</b>\n"
        "• Лофт-Гостиная (4-6 чел.)\n"
        "• Премиум-Бордрум (8-12 чел.)\n"
        "• Стеклянный Опенспейс (6-10 чел.)"
    )


# === ГЛАВНОЕ МЕНЮ (Reply-кнопки) ===

@router.message(F.text == "📅 Забронировать комнату")
async def reply_book_room(message: Message, state: FSMContext):
    await state.set_state(BookingStates.selecting_room)
    await message.answer(
        "🏢 Выберите переговорную комнату:",
        reply_markup=get_rooms_keyboard()
    )


@router.message(F.text == "📋 Брони на сегодня")
async def reply_today_bookings(message: Message):
    today_str = datetime.now().strftime("%d.%m.%Y")
    bookings = await db.get_bookings_by_date(today_str)

    if not bookings:
        await message.answer(
            f"📅 <b>Бронирования на сегодня ({today_str}):</b>\n\n"
            f"На сегодня бронирований пока нет. Вы можете стать первым!",
            reply_markup=get_main_reply_keyboard()
        )
        return

    text = f"📅 <b>Бронирования на сегодня ({today_str}):</b>\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        username = booking.get("Имя", "—")
        text += (
            f"• <b>{booking['Время Начала']} — {booking['Время Конца']}</b> | "
            f"{room_name} ({username})\n"
        )

    await message.answer(text, reply_markup=get_main_reply_keyboard())


@router.message(F.text == "📅 Брони на дату")
async def reply_view_bookings_date(message: Message, state: FSMContext):
    await state.set_state(BookingStates.viewing_bookings_date)
    await message.answer(
        "📅 Выберите дату для просмотра бронирований:",
        reply_markup=get_view_date_keyboard()
    )


@router.message(F.text == "📋 Мои бронирования")
async def reply_my_bookings(message: Message):
    user_id = str(message.from_user.id)
    bookings = await db.get_user_bookings(user_id, "TG")

    if not bookings:
        await message.answer(
            "📋 У вас пока нет активных бронирований.",
            reply_markup=get_main_reply_keyboard()
        )
        return

    text = "📋 <b>Ваши активные бронирования:</b>\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        text += (
            f"🆔 <b>#{booking['ID брони']}</b>\n"
            f"🏢 {room_name}\n"
            f"📅 {booking['Дата']}\n"
            f"🕐 {booking['Время Начала']} — {booking['Время Конца']}\n"
            f"📝 {booking['Цель']}\n"
            f"——————————————\n"
        )

    first_booking_id = bookings[0]["ID брони"]
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить последнюю бронь", callback_data=f"cancel:{first_booking_id}")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
        ])
    )


# === ИНЛАЙН ОБРАБОТЧИКИ ===

@router.callback_query(F.data == "main_menu")
async def process_main_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "Главное меню. Выберите действие:",
        reply_markup=get_main_menu_inline_keyboard()
    )


@router.callback_query(F.data == "book_room")
async def process_book_room(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BookingStates.selecting_room)

    data = await state.get_data()
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")
    
    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption="🏢 Выберите переговорную комнату:",
            reply_markup=get_rooms_keyboard()
        )
    else:
        await callback.message.edit_text(
            "🏢 Выберите переговорную комнату:",
            reply_markup=get_rooms_keyboard()
        )


@router.callback_query(F.data == "today_bookings")
async def process_today_bookings(callback: CallbackQuery):
    await callback.answer()
    today_str = datetime.now().strftime("%d.%m.%Y")
    bookings = await db.get_bookings_by_date(today_str)

    if not bookings:
        await callback.message.edit_text(
            f"📅 <b>Бронирования на сегодня ({today_str}):</b>\n\n"
            f"На сегодня бронирований пока нет. Вы можете стать первым!",
            reply_markup=get_main_menu_inline_keyboard()
        )
        return

    text = f"📅 <b>Бронирования на сегодня ({today_str}):</b>\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        username = booking.get("Имя", "—")
        text += (
            f"• <b>{booking['Время Начала']} — {booking['Время Конца']}</b> | "
            f"{room_name} ({username})\n"
        )

    await callback.message.edit_text(text, reply_markup=get_main_menu_inline_keyboard())


@router.callback_query(F.data == "view_date_menu")
async def process_view_date_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BookingStates.viewing_bookings_date)
    await callback.message.edit_text(
        "📅 Выберите дату для просмотра бронирований:",
        reply_markup=get_view_date_keyboard()
    )


# === ПРОСМОТР БРОНЕЙ НА ДАТУ ===

@router.callback_query(F.data.startswith("view_date:"))
async def process_view_date_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    date_str = callback.data.split(":", 1)[1]
    bookings = await db.get_bookings_by_date(date_str)

    if not bookings:
        await callback.message.edit_text(
            f"📅 <b>Бронирования на {date_str}:</b>\n\n"
            f"На эту дату бронирований пока нет. Вы можете стать первым!",
            reply_markup=get_main_menu_inline_keyboard()
        )
        await state.clear()
        return

    text = f"📅 <b>Бронирования на {date_str}:</b>\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        username = booking.get("Имя", "—")
        text += (
            f"• <b>{booking['Время Начала']} — {booking['Время Конца']}</b> | "
            f"{room_name} ({username})\n"
        )

    await callback.message.edit_text(text, reply_markup=get_main_menu_inline_keyboard())
    await state.clear()


# === ВЫБОР КОМНАТЫ ===

@router.callback_query(F.data.startswith("room:"))
async def process_room_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    room_id = callback.data.split(":")[1]
    room_data = ROOMS.get(room_id)

    if not room_data:
        await callback.answer("Ошибка: комната не найдена", show_alert=True)
        return

    await state.update_data(room_id=room_id, room_name=room_data["name"])
    await state.set_state(BookingStates.selecting_date)

    features_text = "\n".join([f"  ✓ {f}" for f in room_data["features"]])
    caption = (
        f"<b>{room_data['name']}</b>\n\n"
        f"{room_data['description']}\n\n"
        f"<b>Вместимость:</b> {room_data['capacity']}\n\n"
        f"<b>Преимущества:</b>\n{features_text}\n\n"
        f"Выберите дату бронирования:"
    )

    try:
        photo = FSInputFile(room_data["image_path"])
        sent_message = await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=get_date_keyboard()
        )
        await state.update_data(photo_message_id=sent_message.message_id, photo_chat_id=sent_message.chat.id)
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        await callback.message.edit_text(caption, reply_markup=get_date_keyboard())


# === ВЫБОР ДАТЫ ===

@router.callback_query(F.data == "back_to_date")
async def process_back_to_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BookingStates.selecting_date)
    
    data = await state.get_data()
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")

    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption="📅 Выберите дату бронирования:",
            reply_markup=get_date_keyboard()
        )
    else:
        await callback.message.edit_text(
            "📅 Выберите дату бронирования:",
            reply_markup=get_date_keyboard()
        )


@router.callback_query(F.data.startswith("date:"))
async def process_date_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    date_str = callback.data.split(":")[1]
    await state.update_data(date_str=date_str)

    data = await state.get_data()
    room_id = data.get("room_id")

    if not room_id:
        await state.clear()
        await callback.message.edit_text(
            "Главное меню. Выберите действие:",
            reply_markup=get_main_menu_inline_keyboard()
        )
        return

    available_slots = await db.get_available_slots(date_str, room_id)

    if not available_slots:
        photo_msg_id = data.get("photo_message_id")
        photo_chat_id = data.get("photo_chat_id")
        if photo_msg_id and photo_chat_id:
            await bot.edit_message_caption(
                chat_id=photo_chat_id,
                message_id=photo_msg_id,
                caption=f"📅 На {date_str} все слоты заняты.\n\nВыберите другую дату:",
                reply_markup=get_date_keyboard()
            )
        else:
            await callback.message.edit_text(
                f"📅 На {date_str} все слоты заняты.\n\nВыберите другую дату:",
                reply_markup=get_date_keyboard()
            )
        return

    await state.set_state(BookingStates.selecting_start_time)
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")
    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption=f"📅 <b>{date_str}</b>\n\nВыберите время начала встречи:",
            reply_markup=get_time_keyboard(available_slots, date_str)
        )
    else:
        await callback.message.edit_text(
            f"📅 <b>{date_str}</b>\n\nВыберите время начала встречи:",
            reply_markup=get_time_keyboard(available_slots, date_str)
        )


# === ВЫБОР ВРЕМЕНИ ===

@router.callback_query(F.data == "back_to_time")
async def process_back_to_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    date_str = data.get("date_str", "")
    room_id = data.get("room_id", "")

    available_slots = await db.get_available_slots(date_str, room_id)
    await state.set_state(BookingStates.selecting_start_time)
    
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")
    
    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption=f"📅 <b>{date_str}</b>\n\nВыберите время начала встречи:",
            reply_markup=get_time_keyboard(available_slots, date_str)
        )
    else:
        await callback.message.edit_text(
            f"📅 <b>{date_str}</b>\n\nВыберите время начала встречи:",
            reply_markup=get_time_keyboard(available_slots, date_str)
        )


@router.callback_query(F.data.startswith("time:"))
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    start_time = callback.data.split(":", 1)[1]
    await state.update_data(start_time=start_time)

    await state.set_state(BookingStates.selecting_duration)
    
    data = await state.get_data()
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")
    
    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption=f"🕐 Начало: <b>{start_time}</b>\n\nВыберите длительность встречи:",
            reply_markup=get_duration_keyboard(start_time)
        )
    else:
        await callback.message.edit_text(
            f"🕐 Начало: <b>{start_time}</b>\n\n"
            f"Выберите длительность встречи:",
            reply_markup=get_duration_keyboard(start_time)
        )


# === ВЫБОР ДЛИТЕЛЬНОСТИ ===

@router.callback_query(F.data.startswith("duration:"))
async def process_duration_selection(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    duration_minutes = int(callback.data.split(":")[1])
    await state.update_data(duration_minutes=duration_minutes)

    data = await state.get_data()
    start_time = data["start_time"]
    date_str = data["date_str"]

    if ":" not in start_time:
        start_time = f"{start_time}:00"

    start_dt = datetime.strptime(f"{date_str} {start_time}", "%d.%m.%Y %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    end_time = end_dt.strftime("%H:%M")

    await state.update_data(end_time=end_time)

    await state.set_state(BookingStates.entering_purpose)
    
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")
    
    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption=f"⏱ Длительность: <b>{duration_minutes} мин.</b>\n🕐 {start_time} — {end_time}\n\nВведите цель встречи (краткое описание):",
            reply_markup=None
        )
    else:
        await callback.message.edit_text(
            f"⏱ Длительность: <b>{duration_minutes} мин.</b>\n"
            f"🕐 {start_time} — {end_time}\n\n"
            f"Введите цель встречи (краткое описание):"
        )


# === ВВОД ЦЕЛИ ===

@router.message(BookingStates.entering_purpose)
async def process_purpose(message: Message, state: FSMContext):
    purpose = message.text.strip()

    if len(purpose) < 2:
        await message.answer("⚠️ Описание слишком короткое. Введите более подробную цель:")
        return

    if len(purpose) > 200:
        await message.answer("⚠️ Описание слишком длинное (макс. 200 символов). Введите кратче:")
        return

    await state.update_data(purpose=purpose)
    data = await state.get_data()

    summary = (
        f"📋 <b>Проверьте данные бронирования:</b>\n\n"
        f"🏢 Комната: <b>{data['room_name']}</b>\n"
        f"📅 Дата: <b>{data['date_str']}</b>\n"
        f"🕐 Время: <b>{data['start_time']} — {data['end_time']}</b>\n"
        f"📝 Цель: <b>{purpose}</b>\n\n"
        f"Подтвердите бронирование:"
    )

    await state.set_state(BookingStates.confirming)
    await message.answer(summary, reply_markup=get_confirm_keyboard())


# === ПОДТВЕРЖДЕНИЕ ===

@router.callback_query(F.data == "cancel_booking")
async def process_cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Бронирование отменено")
    await state.clear()

    data = await state.get_data()
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")

    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption="❌ Бронирование отменено.\n\nВыберите действие:",
            reply_markup=get_main_menu_inline_keyboard()
        )
    else:
        await callback.message.edit_text(
            "❌ Бронирование отменено.\n\nВыберите действие:",
            reply_markup=get_main_menu_inline_keyboard()
        )


@router.callback_query(F.data == "confirm_booking")
async def process_confirm_booking(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Создаем бронирование...")
    data = await state.get_data()

    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")

    # Безопасно получаем данные
    room_id = data.get("room_id") or data.get("room") or "glass_openspace"
    room_name = data.get("room_name") or ROOMS.get(room_id, {}).get("name", "Переговорная")
    date_str = data.get("date_str") or "—"
    start_time = data.get("start_time") or "—"
    end_time = data.get("end_time") or "—"
    purpose = data.get("purpose") or "—"

    # Получаем username пользователя (ник или имя)
    username = callback.from_user.username
    if not username:
        username = callback.from_user.first_name or "Пользователь"
    else:
        username = f"@{username}"

    try:
        booking_id = await db.create_booking(
            user_name=username,
            platform="TG",
            user_id=str(callback.from_user.id),
            room_id=room_id,
            date_str=date_str,
            start_time_str=start_time,
            end_time_str=end_time,
            purpose=purpose
        )

        # Формируем финальное сообщение
        caption = (
            f"🎉 <b>Успешно забронировано!</b>\n\n"
            f"📍 <b>Комната:</b> {room_name}\n"
            f"📅 <b>Дата:</b> {date_str}\n"
            f"⏰ <b>Время:</b> {start_time} — {end_time}\n"
            f"🆔 <b>Номер брони:</b> #{booking_id}\n\n"
            f"Ждем вас на встрече!"
        )

        # Убираем инлайн-кнопки под фото
        if photo_msg_id and photo_chat_id:
            await bot.edit_message_caption(
                chat_id=photo_chat_id,
                message_id=photo_msg_id,
                caption=caption,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(caption)

        # Очищаем стейт
        await state.clear()

        # Автоматический возврат в главное меню с Reply-кнопками
        await callback.message.answer(
            "👋 Вы вернулись в главное меню. Выберите действие:",
            reply_markup=get_main_reply_keyboard()
        )

    except BookingConflictError as e:
        await callback.answer(str(e), show_alert=True)
        await state.set_state(BookingStates.selecting_start_time)
        available_slots = await db.get_available_slots(date_str, room_id)
        caption = f"⚠️ {str(e)}\n\nВыберите другое время:"
        if photo_msg_id and photo_chat_id:
            await bot.edit_message_caption(
                chat_id=photo_chat_id,
                message_id=photo_msg_id,
                caption=caption,
                reply_markup=get_time_keyboard(available_slots, date_str)
            )
        else:
            await callback.message.edit_text(
                caption,
                reply_markup=get_time_keyboard(available_slots, date_str)
            )

    except ValidationError as e:
        await callback.answer(str(e), show_alert=True)
        caption = f"⚠️ Ошибка: {str(e)}\n\nПопробуйте снова:"
        if photo_msg_id and photo_chat_id:
            await bot.edit_message_caption(
                chat_id=photo_chat_id,
                message_id=photo_msg_id,
                caption=caption,
                reply_markup=get_main_menu_inline_keyboard()
            )
        else:
            await callback.message.edit_text(
                caption,
                reply_markup=get_main_menu_inline_keyboard()
            )
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка создания бронирования: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)


# === МОИ БРОНИРОВАНИЯ ===

@router.callback_query(F.data == "my_bookings")
async def process_my_bookings(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = str(callback.from_user.id)
    bookings = await db.get_user_bookings(user_id, "TG")

    data = await state.get_data()
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")

    if not bookings:
        caption = "📋 У вас пока нет активных бронирований.\n\nХотите забронировать комнату?"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Забронировать", callback_data="book_room")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
        ])
        if photo_msg_id and photo_chat_id:
            await bot.edit_message_caption(
                chat_id=photo_chat_id,
                message_id=photo_msg_id,
                caption=caption,
                reply_markup=keyboard
            )
        else:
            await callback.message.edit_text(caption, reply_markup=keyboard)
        return

    caption = "📋 <b>Ваши активные бронирования:</b>\n\n"
    for booking in bookings:
        room_name = ROOMS.get(booking.get("Переговорка"), {}).get("name", booking.get("Переговорка"))
        caption += (
            f"🆔 <b>#{booking['ID брони']}</b>\n"
            f"🏢 {room_name}\n"
            f"📅 {booking['Дата']}\n"
            f"🕐 {booking['Время Начала']} — {booking['Время Конца']}\n"
            f"📝 {booking['Цель']}\n"
            f"——————————————\n"
        )

    first_booking_id = bookings[0]["ID брони"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить последнюю бронь", callback_data=f"cancel:{first_booking_id}")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
    ])

    if photo_msg_id and photo_chat_id:
        await bot.edit_message_caption(
            chat_id=photo_chat_id,
            message_id=photo_msg_id,
            caption=caption,
            reply_markup=keyboard
        )
    else:
        await callback.message.edit_text(caption, reply_markup=keyboard)


@router.callback_query(F.data.startswith("cancel:"))
async def process_cancel_specific_booking(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Отменяем бронирование...")
    try:
        booking_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка: неверный ID бронирования", show_alert=True)
        return

    user_id = str(callback.from_user.id)
    success = await db.cancel_booking(booking_id, user_id, "TG")

    data = await state.get_data()
    photo_msg_id = data.get("photo_message_id")
    photo_chat_id = data.get("photo_chat_id")

    if success:
        caption = f"✅ Бронирование <b>#{booking_id}</b> успешно отменено.\n\nВыберите действие:"
        if photo_msg_id and photo_chat_id:
            await bot.edit_message_caption(
                chat_id=photo_chat_id,
                message_id=photo_msg_id,
                caption=caption,
                reply_markup=get_main_menu_inline_keyboard()
            )
        else:
            await callback.message.edit_text(
                caption,
                reply_markup=get_main_menu_inline_keyboard()
            )
    else:
        await callback.answer(
            "Не удалось отменить бронирование. Возможно, оно уже прошло или не существует.",
            show_alert=True
        )


# === ЗАПУСК ===

dp.include_router(router)


async def start_telegram_bot():
    """Запускает Telegram-бота в режиме long-polling."""
    logger.info("Запуск Telegram-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
