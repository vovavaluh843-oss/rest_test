"""
Модуль для работы с Google Sheets.
Реализует слой доступа к данным для системы бронирования.

Особенности:
- Асинхронная работа с Google Sheets через gspread
- Блокировки (asyncio.Lock) для предотвращения race condition
- Экранирование пользовательских данных для защиты от инъекций
- Валидация дат и времени
"""

import asyncio
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple

import gspread
from gspread import Worksheet, Spreadsheet
from oauth2client.service_account import ServiceAccountCredentials

from config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SPREADSHEET_ID,
    BOOKINGS_SHEET_NAME,
    BOOKING_STEP_MINUTES,
    MAX_BOOKING_HOURS,
    WORK_DAY_START,
    WORK_DAY_END,
    ROOMS,
)

logger = logging.getLogger(__name__)

# Символы, которые могут использоваться для формульных инъекций
DANGEROUS_CHARS = ['=', '+', '-', '@', '\t', '\r', '\n']
INJECTION_PATTERN = re.compile(r'^[\=\+\-\@\t\r\n]+')

# Блокировки для каждой комнаты (защита от race condition)
ROOM_LOCKS: Dict[str, asyncio.Lock] = {
    room_id: asyncio.Lock() for room_id in ROOMS.keys()
}
ID_LOCK = asyncio.Lock()


class DatabaseError(Exception):
    """Базовое исключение для ошибок работы с базой данных."""
    pass


class BookingConflictError(DatabaseError):
    """Исключение при попытке забронировать уже занятый слот."""
    pass


class ValidationError(DatabaseError):
    """Исключение при невалидных данных бронирования."""
    pass


class GoogleSheetsDB:
    """
    Класс для работы с Google Sheets как с базой данных.
    Использует паттерн Singleton для переиспользования соединения.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._client = None
        self._spreadsheet = None
        self._bookings_sheet = None
        self._initialized = True

    async def connect(self):
        """Устанавливает соединение с Google Sheets API."""
        if self._client is not None:
            return

        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(
                GOOGLE_SERVICE_ACCOUNT_FILE,
                scopes=[
                    'https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive'
                ]
            )
            self._client = gspread.authorize(credentials)
            self._spreadsheet = self._client.open_by_key(GOOGLE_SPREADSHEET_ID)

            try:
                self._bookings_sheet = self._spreadsheet.worksheet(BOOKINGS_SHEET_NAME)
            except gspread.WorksheetNotFound:
                self._bookings_sheet = await self._create_bookings_sheet()

            logger.info("Успешное подключение к Google Sheets")
        except Exception as e:
            logger.error(f"Ошибка подключения к Google Sheets: {e}")
            raise DatabaseError(f"Не удалось подключиться к Google Sheets: {e}")

    async def _create_bookings_sheet(self):
        """Создает лист bookings с заголовками."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_create_sheet)

    def _sync_create_sheet(self):
        sheet = self._spreadsheet.add_worksheet(title=BOOKINGS_SHEET_NAME, rows=1000, cols=9)
        headers = ["ID брони", "Имя", "Платформа", "ID пользователя",
                   "Переговорка", "Дата", "Время Начала", "Время Конца", "Цель"]
        sheet.append_row(headers)
        sheet.format('A1:I1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })
        return sheet

    @staticmethod
    def sanitize_input(value):
        """
        Очищает пользовательский ввод от опасных символов.
        Предотвращает формульные инъекции в Google Sheets.
        """
        if value is None:
            return ""
        text = str(value).strip()
        text = INJECTION_PATTERN.sub('', text)
        for char in DANGEROUS_CHARS:
            text = text.replace(char, ' ')
        return text[:500]

    @staticmethod
    def validate_booking_time(date_str, start_time_str, end_time_str):
        """
        Валидирует время бронирования.
        Правила: запрет прошедшего времени, шаг 30 мин, макс 3 часа, рабочие часы 9-18.
        """
        try:
            date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()
        except ValueError:
            raise ValidationError("Неверный формат даты или времени")

        now = datetime.now()
        start_dt = datetime.combine(date_obj, start_time)
        end_dt = datetime.combine(date_obj, end_time)

        # Проверка на прошедшее время
        if start_dt < now:
            raise ValidationError("Нельзя бронировать на прошедшее время")

        # Проверка округления до 30 минут
        if start_time.minute not in [0, 30] or start_time.second != 0:
            raise ValidationError(f"Время должно быть кратно {BOOKING_STEP_MINUTES} минутам")
        if end_time.minute not in [0, 30] or end_time.second != 0:
            raise ValidationError(f"Время должно быть кратно {BOOKING_STEP_MINUTES} минутам")

        # Проверка рабочих часов (9:00 - 18:00)
        if start_time.hour < WORK_DAY_START or end_time.hour > WORK_DAY_END:
            raise ValidationError(f"Бронирование доступно с {WORK_DAY_START}:00 до {WORK_DAY_END}:00")
        if end_time.hour == WORK_DAY_END and end_time.minute > 0:
            raise ValidationError(f"Бронирование должно закончиться не позже {WORK_DAY_END}:00")

        # Проверка длительности
        duration = end_dt - start_dt
        max_duration = timedelta(hours=MAX_BOOKING_HOURS)
        if duration <= timedelta(0):
            raise ValidationError("Время окончания должно быть позже времени начала")
        if duration > max_duration:
            raise ValidationError(f"Максимальная длительность бронирования — {MAX_BOOKING_HOURS} часа")

        return start_dt, end_dt

    async def get_all_bookings(self):
        """Получает все бронирования из таблицы."""
        await self.connect()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_all_bookings)

    def _sync_get_all_bookings(self):
        records = self._bookings_sheet.get_all_records()
        return records

    async def get_bookings_by_date_and_room(self, date_str, room_id):
        """Получает бронирования для конкретной комнаты и даты."""
        await self.connect()
        all_bookings = await self.get_all_bookings()
        filtered = [
            booking for booking in all_bookings
            if booking.get("Дата") == date_str and booking.get("Переговорка") == room_id
        ]
        return filtered

    async def get_user_bookings(self, user_id, platform):
        """Получает активные бронирования пользователя."""
        await self.connect()
        all_bookings = await self.get_all_bookings()
        now = datetime.now()
        user_bookings = []

        for booking in all_bookings:
            if (str(booking.get("ID пользователя")) == str(user_id) and
                    booking.get("Платформа") == platform):
                try:
                    date_str = booking.get("Дата", "")
                    end_time_str = booking.get("Время Конца", "")
                    end_dt = datetime.strptime(f"{date_str} {end_time_str}", "%d.%m.%Y %H:%M")
                    if end_dt > now:
                        user_bookings.append(booking)
                except (ValueError, TypeError):
                    continue
        return user_bookings

    async def check_slot_availability(self, date_str, room_id, start_time_str, end_time_str):
        """Проверяет, свободен ли слот для бронирования."""
        bookings = await self.get_bookings_by_date_and_room(date_str, room_id)
        new_start = datetime.strptime(f"{date_str} {start_time_str}", "%d.%m.%Y %H:%M")
        new_end = datetime.strptime(f"{date_str} {end_time_str}", "%d.%m.%Y %H:%M")

        for booking in bookings:
            try:
                existing_start = datetime.strptime(
                    f"{booking['Дата']} {booking['Время Начала']}", "%d.%m.%Y %H:%M")
                existing_end = datetime.strptime(
                    f"{booking['Дата']} {booking['Время Конца']}", "%d.%m.%Y %H:%M")
            except (ValueError, KeyError):
                continue

            # Проверка пересечения интервалов
            if new_start < existing_end and new_end > existing_start:
                return False
        return True

    async def create_booking(self, user_name, platform, user_id, room_id,
                             date_str, start_time_str, end_time_str, purpose):
        """
        Создает новое бронирование с защитой от race condition.
        Алгоритм: валидация -> блокировка комнаты -> повторная проверка -> запись.
        """
        # Валидация времени
        self.validate_booking_time(date_str, start_time_str, end_time_str)

        # Очистка пользовательских данных
        safe_name = self.sanitize_input(user_name)
        safe_purpose = self.sanitize_input(purpose)
        safe_platform = self.sanitize_input(platform)
        safe_user_id = self.sanitize_input(user_id)
        safe_room_id = self.sanitize_input(room_id)

        # Блокировка для конкретной комнаты
        room_lock = ROOM_LOCKS.get(room_id)
        if room_lock is None:
            raise ValidationError(f"Неизвестная комната: {room_id}")

        async with room_lock:
            # ДВОЙНАЯ ПРОВЕРКА: повторно проверяем доступность слота
            is_available = await self.check_slot_availability(
                date_str, room_id, start_time_str, end_time_str)

            if not is_available:
                raise BookingConflictError(
                    "Этот слот только что был занят другим пользователем. "
                    "Пожалуйста, выберите другое время."
                )

            # Генерация ID бронирования
            async with ID_LOCK:
                booking_id = await self._get_next_booking_id()

            # Запись в Google Sheets
            await self._append_booking_row(
                booking_id, safe_name, safe_platform, safe_user_id, safe_room_id,
                date_str, start_time_str, end_time_str, safe_purpose)

            logger.info(f"Создано бронирование #{booking_id}: {safe_room_id} "
                        f"на {date_str} {start_time_str}-{end_time_str}")
            return booking_id

    async def _get_next_booking_id(self):
        """Получает следующий свободный ID бронирования."""
        await self.connect()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_next_id)

    def _sync_get_next_id(self):
        all_values = self._bookings_sheet.get_all_values()
        if len(all_values) <= 1:
            return 1
        max_id = 0
        for row in all_values[1:]:
            if row and row[0]:
                try:
                    current_id = int(row[0])
                    max_id = max(max_id, current_id)
                except (ValueError, IndexError):
                    continue
        return max_id + 1

    async def _append_booking_row(self, booking_id, user_name, platform, user_id,
                                  room_id, date_str, start_time_str, end_time_str, purpose):
        """Добавляет строку бронирования в таблицу."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_append_row,
            [booking_id, user_name, platform, user_id, room_id,
             date_str, start_time_str, end_time_str, purpose])

    def _sync_append_row(self, row_data):
        self._bookings_sheet.append_row(row_data)

    async def cancel_booking(self, booking_id, user_id, platform):
        """Отменяет бронирование пользователя."""
        await self.connect()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_cancel_booking, booking_id, user_id, platform)

    def _sync_cancel_booking(self, booking_id, user_id, platform):
        all_values = self._bookings_sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 4:
                continue
            try:
                row_id = int(row[0])
                row_platform = row[2]
                row_user_id = str(row[3])
                if row_id == booking_id and row_platform == platform and row_user_id == str(user_id):
                    self._bookings_sheet.delete_rows(idx)
                    logger.info(f"Бронирование #{booking_id} отменено")
                    return True
            except (ValueError, IndexError):
                continue
        return False

    async def get_available_slots(self, date_str, room_id):
        """Получает список свободных слотов для бронирования."""
        bookings = await self.get_bookings_by_date_and_room(date_str, room_id)
        slots = []
        current_hour = WORK_DAY_START
        current_minute = 0

        while current_hour < WORK_DAY_END:
            start_str = f"{current_hour:02d}:{current_minute:02d}"
            end_minute = current_minute + BOOKING_STEP_MINUTES
            end_hour = current_hour
            if end_minute >= 60:
                end_minute = 0
                end_hour += 1
            if end_hour > WORK_DAY_END:
                break
            end_str = f"{end_hour:02d}:{end_minute:02d}"

            is_free = True
            slot_start = datetime.strptime(f"{date_str} {start_str}", "%d.%m.%Y %H:%M")
            slot_end = datetime.strptime(f"{date_str} {end_str}", "%d.%m.%Y %H:%M")

            for booking in bookings:
                try:
                    b_start = datetime.strptime(
                        f"{booking['Дата']} {booking['Время Начала']}", "%d.%m.%Y %H:%M")
                    b_end = datetime.strptime(
                        f"{booking['Дата']} {booking['Время Конца']}", "%d.%m.%Y %H:%M")
                except (ValueError, KeyError):
                    continue
                if slot_start < b_end and slot_end > b_start:
                    is_free = False
                    break

            if is_free:
                slots.append((start_str, end_str))

            current_minute += BOOKING_STEP_MINUTES
            if current_minute >= 60:
                current_minute = 0
                current_hour += 1

        return slots


# Глобальный экземпляр базы данных
db = GoogleSheetsDB()
