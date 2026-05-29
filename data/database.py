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
import os
import re
import logging
from datetime import datetime, timedelta, timezone
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
    TIMEZONE,
)

# Название листа для авторизации пользователей
USERS_AUTH_SHEET_NAME = "users_auth"
AUTH_CODE_EXPIRY_MINUTES = 10  # Время жизни кода авторизации

# Получаем абсолютный путь к папке data/, где лежит текущий database.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE_NAME = "service_account.json"
CREDENTIALS_PATH = os.path.join(BASE_DIR, KEY_FILE_NAME)

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
        self._users_auth_sheet = None
        self._initialized = True

    async def connect(self):
        """Устанавливает соединение с Google Sheets API."""
        if self._client is not None:
            return

        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(
                CREDENTIALS_PATH,
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

            # Инициализация листа пользователей
            try:
                self._users_auth_sheet = self._spreadsheet.worksheet(USERS_AUTH_SHEET_NAME)
            except gspread.WorksheetNotFound:
                self._users_auth_sheet = await self._create_users_auth_sheet()

            logger.info("Успешное подключение к Google Sheets")
        except Exception as e:
            logger.error(f"Ошибка подключения к Google Sheets: {e}")
            raise DatabaseError(f"Не удалось подключиться к Google Sheets: {e}")

    async def _create_bookings_sheet(self):
        """Создает лист bookings с заголовками."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_create_sheet)

    def _sync_create_sheet(self):
        sheet = self._spreadsheet.add_worksheet(title=BOOKINGS_SHEET_NAME, rows=1000, cols=11)
        headers = ["ID брони", "Имя", "Платформа", "ID пользователя",
                   "Переговорка", "Дата", "Время Начала", "Время Конца", "Цель", "Статус", "Уведомление"]
        sheet.append_row(headers)
        sheet.format('A1:K1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })
        return sheet

    async def _create_users_auth_sheet(self):
        """Создает лист users_auth с заголовками."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_create_users_auth_sheet)

    def _sync_create_users_auth_sheet(self):
        sheet = self._spreadsheet.add_worksheet(title=USERS_AUTH_SHEET_NAME, rows=1000, cols=5)
        headers = ["telegram_id", "vk_id", "name", "auth_code", "code_expires"]
        sheet.append_row(headers)
        sheet.format('A1:E1', {
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

        now = datetime.now(TIMEZONE)
        start_dt = datetime.combine(date_obj, start_time).replace(tzinfo=TIMEZONE)
        end_dt = datetime.combine(date_obj, end_time).replace(tzinfo=TIMEZONE)

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
        """Получает активные бронирования для конкретной комнаты и даты."""
        await self.connect()
        all_bookings = await self.get_all_bookings()
        filtered = [
            booking for booking in all_bookings
            if booking.get("Дата") == date_str
            and booking.get("Переговорка") == room_id
            and booking.get("Статус", "Активно") == "Активно"
        ]
        return filtered

    async def get_bookings_by_date(self, date_str):
        """Получает активные бронирования на конкретную дату."""
        await self.connect()
        all_bookings = await self.get_all_bookings()
        filtered = [
            booking for booking in all_bookings
            if booking.get("Дата") == date_str
            and booking.get("Статус", "Активно") == "Активно"
        ]
        return filtered
        
    async def get_user_bookings(self, user_id, platform):
        """Получает активные бронирования пользователя (с проверкой связанных аккаунтов)."""
        await self.connect()
        
        # Получаем связанные ID аккаунтов (и TG, и VK)
        linked_ids = await self.get_linked_user_ids(user_id, platform)
        
        now = datetime.now(TIMEZONE)
        user_bookings = []

        for booking in await self.get_all_bookings():
            # Проверяем статус бронирования
            if booking.get("Статус", "Активно") != "Активно":
                continue

            # Проверяем, принадлежит ли бронь любому из связанных ID
            booking_user_id = str(booking.get("ID пользователя", ""))
            
            # Бронь принадлежит пользователю, если ID совпадает (не важно какая платформа)
            if booking_user_id in linked_ids:
                try:
                    date_str = booking.get("Дата", "")
                    end_time_str = booking.get("Время Конца", "")
                    end_dt = datetime.strptime(f"{date_str} {end_time_str}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)
                    if end_dt > now:
                        user_bookings.append(booking)
                except (ValueError, TypeError):
                    continue
        return user_bookings
        
    async def get_linked_user_ids(self, user_id, platform):
        """Получает список связанных ID для пользователя (для кросс-платформенного доступа)."""
        await self.connect()
        linked_ids = {str(user_id)}  # Всегда включаем текущий ID
        
        try:
            records = await self._get_all_users_auth()
            for record in records:
                tg_id = str(record.get("telegram_id", ""))
                vk_id = str(record.get("vk_id", ""))
                
                if platform == "TG":
                    # Если текущий Telegram ID найден, добавляем VK ID
                    if tg_id == str(user_id) and vk_id:
                        linked_ids.add(vk_id)
                elif platform == "VK":
                    # Если текущий VK ID найден, добавляем Telegram ID
                    if vk_id == str(user_id) and tg_id:
                        linked_ids.add(tg_id)
        except Exception as e:
            logger.error(f"Ошибка при получении связанных ID: {e}")
        
        return linked_ids

    async def _get_all_users_auth(self):
        """Получает все записи из таблицы пользователей."""
        try:
            records = await self.connect() or self._users_auth_sheet
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_get_all_users_auth)
        except Exception:
            return []

    def _sync_get_all_users_auth(self):
        try:
            return self._users_auth_sheet.get_all_records()
        except Exception:
            return []

    async def generate_auth_code(self, telegram_id: str, name: str) -> str:
        """
        Генерирует 6-значный код авторизации для связки аккаунтов.
        Сохраняет в таблицу users_auth с истекающим временем.
        """
        await self.connect()
        
        # Генерируем случайный код
        import random
        code = f"TGVK{random.randint(1000, 9999)}"
        expires = datetime.now(TIMEZONE) + timedelta(minutes=AUTH_CODE_EXPIRY_MINUTES)
        expires_str = expires.strftime("%d.%m.%Y %H:%M")
        
        # Проверяем, есть ли уже активный код для этого telegram_id
        existing = await self._get_user_auth_record(telegram_id)
        
        loop = asyncio.get_event_loop()
        if existing:
            # Обновляем существующую запись
            await loop.run_in_executor(
                None, self._sync_update_user_auth, telegram_id, name, code, expires_str)
        else:
            # Создаем новую запись
            await loop.run_in_executor(
                None, self._sync_append_user_auth, telegram_id, "", name, code, expires_str)
        
        logger.info(f"Сгенерирован код {code} для Telegram ID {telegram_id}")
        return code

    async def _get_user_auth_record(self, telegram_id: str):
        """Получает запись авторизации для telegram_id."""
        try:
            records = await self._get_all_users_auth()
            for record in records:
                if str(record.get("telegram_id", "")) == str(telegram_id):
                    return record
        except Exception:
            pass
        return None

    def _sync_update_user_auth(self, telegram_id: str, vk_id: str, name: str, code: str, expires: str):
        """Обновляет запись авторизации."""
        all_values = self._users_auth_sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if len(row) >= 1 and str(row[0]) == str(telegram_id):
                self._users_auth_sheet.update(f'A{idx}:E{idx}', [[telegram_id, vk_id, name, code, expires]])
                return

    def _sync_append_user_auth(self, telegram_id: str, vk_id: str, name: str, code: str, expires: str):
        """Добавляет новую запись авторизации."""
        self._users_auth_sheet.append_row([telegram_id, vk_id, name, code, expires])

    async def link_vk_account(self, vk_id: str, auth_code: str) -> bool:
        """
        Связывает VK аккаунт с найденным по коду Telegram аккаунтом.
        Возвращает True при успехе.
        """
        await self.connect()
        
        # Проверяем, не истёк ли код
        records = await self._get_all_users_auth()
        for record in records:
            if str(record.get("auth_code", "")) == auth_code:
                expires_str = record.get("code_expires", "")
                try:
                    expires = datetime.strptime(expires_str, "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)
                    if datetime.now(TIMEZONE) > expires:
                        # Код истёк - удаляем запись
                        self._sync_delete_user_auth_by_code(auth_code)
                        return False
                    
                    # Обновляем запись, записывая vk_id
                    telegram_id = str(record.get("telegram_id", ""))
                    name = str(record.get("name", ""))
                    self._sync_update_user_auth(telegram_id, vk_id, name, auth_code, expires_str)
                    
                    logger.info(f"Связаны аккаунты: TG={telegram_id}, VK={vk_id}")
                    return True
                except (ValueError, TypeError):
                    continue
        
        return False

    def _sync_delete_user_auth_by_code(self, auth_code: str):
        """Удаляет запись авторизации по коду."""
        all_values = self._users_auth_sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if len(row) >= 4 and row[3] == auth_code:
                self._users_auth_sheet.delete_rows(idx)
                return

    async def check_slot_availability(self, date_str, room_id, start_time_str, end_time_str):
        """Проверяет, свободен ли слот для бронирования."""
        bookings = await self.get_bookings_by_date_and_room(date_str, room_id)
        new_start = datetime.strptime(f"{date_str} {start_time_str}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)
        new_end = datetime.strptime(f"{date_str} {end_time_str}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)

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
                date_str, start_time_str, end_time_str, safe_purpose, "Активно", "Нет")

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
                                  room_id, date_str, start_time_str, end_time_str, purpose, status="Активно", notification_sent="Нет"):
        """Добавляет строку бронирования в таблицу."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._sync_append_row,
            [booking_id, user_name, platform, user_id, room_id,
             date_str, start_time_str, end_time_str, purpose, status, notification_sent])

    def _sync_append_row(self, row_data):
        self._bookings_sheet.append_row(row_data)

    async def cancel_booking(self, booking_id, user_id, platform):
        """
        Отменяет бронирование пользователя по ID брони (с проверкой связанных аккаунтов).
        Вместо удаления строки устанавливает статус "Отменено" (soft delete).
        
        Returns:
            tuple: (success: bool, already_cancelled: bool)
                success - удалось ли отменить бронь
                already_cancelled - была ли бронь уже отменена ранее
        """
        await self.connect()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_cancel_booking, booking_id, user_id)

    def _sync_cancel_booking(self, booking_id, user_id):
        """
        Устанавливает статус "Отменено" для бронирования (soft delete).
        
        Returns:
            tuple: (success: bool, already_cancelled: bool)
        """
        # 1. Получаем все связанные ID для пользователя
        allowed_ids = {str(user_id)}
        
        try:
            records = self._sync_get_all_users_auth()
            for record in records:
                tg_id = str(record.get("telegram_id", ""))
                vk_id = str(record.get("vk_id", ""))
                
                if tg_id == str(user_id) and vk_id:
                    allowed_ids.add(vk_id)
                if vk_id == str(user_id) and tg_id:
                    allowed_ids.add(tg_id)
        except Exception as e:
            logger.error(f"Ошибка при получении связанных ID для отмены брони: {e}")
        
        # 2. Ищем бронь и проверяем статус
        all_values = self._bookings_sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 4:
                continue
            try:
                row_id = int(row[0])
                row_user_id = str(row[3])
                row_status = row[9] if len(row) > 9 else "Активно"
                
                # Проверяем: ID брони совпадает И ID пользователя в allowed_ids
                if row_id == booking_id and row_user_id in allowed_ids:
                    # Проверяем, не отменена ли уже
                    if row_status == "Отменено":
                        logger.info(f"Бронирование #{booking_id} уже было отменено ранее")
                        return False, True
                    
                    # Soft delete: обновляем статус вместо удаления
                    self._bookings_sheet.update_cell(idx, 10, "Отменено")
                    logger.info(f"Бронирование #{booking_id} отменено (soft delete) пользователем {user_id}")
                    return True, False
            except (ValueError, IndexError):
                continue
        return False, False

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
            slot_start = datetime.strptime(f"{date_str} {start_str}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)
            slot_end = datetime.strptime(f"{date_str} {end_str}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)

            for booking in bookings:
                try:
                    b_start = datetime.strptime(
                        f"{booking['Дата']} {booking['Время Начала']}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)
                    b_end = datetime.strptime(
                        f"{booking['Дата']} {booking['Время Конца']}", "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)
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

    async def get_bookings_needing_reminders(self, reminder_minutes: int = 30):
        """
        Получает брони, к которым осталось reminder_minutes минут до начала.
        Возвращает только активные брони, для которых ещё не отправлено уведомление.
        """
        await self.connect()
        now = datetime.now(TIMEZONE)
        bookings_to_remind = []

        for booking in await self.get_all_bookings():
            # Проверяем статус и уведомление
            if booking.get("Статус", "Активно") != "Активно":
                continue
            if booking.get("Уведомление", "Нет") == "Отправлено":
                continue
            
            # Проверяем дату (только сегодня)
            booking_date = booking.get("Дата", "")
            today_str = now.strftime("%d.%m.%Y")
            if booking_date != today_str:
                continue
            
            # Проверяем время начала
            try:
                start_time_str = booking.get("Время Начала", "")
                start_dt = datetime.strptime(f"{booking_date} {start_time_str}", "%d.%m.%Y %H:%M")
                start_dt = start_dt.replace(tzinfo=TIMEZONE)
                
                # Разница в минутах
                diff_minutes = (start_dt - now).total_seconds() / 60
                
                # Если осталось от 29 до 31 минуты (попадание в 30-минутное окно)
                if 29 <= diff_minutes <= 31:
                    bookings_to_remind.append(booking)
            except (ValueError, TypeError):
                continue
        
        return bookings_to_remind

    async def mark_reminder_sent(self, booking_id: int):
        """Отмечает, что уведомление для брони было отправлено."""
        await self.connect()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_mark_reminder_sent, booking_id)

    def _sync_mark_reminder_sent(self, booking_id: int):
        """Отмечает в таблице, что уведомление отправлено."""
        all_values = self._bookings_sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 1:
                continue
            try:
                row_id = int(row[0])
                if row_id == booking_id:
                    # Обновляем колонку K (11-я колонка, индекс 10)
                    self._bookings_sheet.update_cell(idx, 11, "Отправлено")
                    logger.info(f"Уведомление для брони #{booking_id} помечено как отправленное")
                    return True
            except (ValueError, IndexError):
                continue
        return False

    # === АДМИН-МЕТОДЫ ===

    async def get_today_stats(self) -> dict:
        """
        Получает статистику бронирований за сегодня.
        
        Returns:
            dict: {
                'total': int,           # Всего броней
                'active': int,          # Активных
                'cancelled': int,       # Отменённых
                'top_rooms': list       # Топ комнат [(room_id, count), ...]
            }
        """
        await self.connect()
        today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")
        
        all_bookings = await self.get_all_bookings()
        today_bookings = [
            b for b in all_bookings 
            if b.get("Дата") == today_str
        ]
        
        total = len(today_bookings)
        active = sum(1 for b in today_bookings if b.get("Статус", "Активно") == "Активно")
        cancelled = total - active
        
        # Топ комнат
        room_counts = {}
        for b in today_bookings:
            room_id = b.get("Переговорка", "unknown")
            room_counts[room_id] = room_counts.get(room_id, 0) + 1
        
        top_rooms = sorted(room_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "total": total,
            "active": active,
            "cancelled": cancelled,
            "top_rooms": top_rooms,
            "date": today_str
        }

    async def get_all_unique_users(self) -> list[dict]:
        """
        Получает список всех уникальных пользователей для рассылки.
        Возвращает записи из users_auth.
        
        Returns:
            list[dict]: Список словарей с telegram_id, vk_id, name
        """
        await self.connect()
        try:
            records = await self._get_all_users_auth()
            # Фильтруем пустые записи
            users = []
            for r in records:
                tg_id = r.get("telegram_id", "")
                vk_id = r.get("vk_id", "")
                name = r.get("name", "")
                if tg_id or vk_id:
                    users.append({
                        "telegram_id": str(tg_id) if tg_id else None,
                        "vk_id": str(vk_id) if vk_id else None,
                        "name": name
                    })
            return users
        except Exception as e:
            logger.error(f"Ошибка получения списка пользователей: {e}")
            return []

    async def admin_cancel_booking(self, booking_id: int) -> bool:
        """
        Принудительная отмена бронирования администратором.
        НЕ проверяет права пользователя (allowed_ids).
        
        Args:
            booking_id: ID брони для отмены
            
        Returns:
            bool: True если отменена, False если не найдена или уже отменена
        """
        await self.connect()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_admin_cancel_booking, booking_id)

    def _sync_admin_cancel_booking(self, booking_id: int) -> bool:
        """Синхронная принудительная отмена брони админом."""
        all_values = self._bookings_sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 10:
                continue
            try:
                row_id = int(row[0])
                row_status = row[9] if len(row) > 9 else "Активно"
                
                if row_id == booking_id:
                    if row_status == "Отменено":
                        logger.info(f"Админ: бронь #{booking_id} уже была отменена")
                        return False
                    
                    self._bookings_sheet.update_cell(idx, 10, "Отменено")
                    logger.info(f"Админ принудительно отменил бронь #{booking_id}")
                    return True
            except (ValueError, IndexError):
                continue
        logger.warning(f"Админ: бронь #{booking_id} не найдена")
        return False


# Глобальный экземпляр базы данных
db = GoogleSheetsDB()
