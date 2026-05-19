#!/bin/bash
# Быстрый запуск ботов

echo "🚀 Запуск системы бронирования..."
source venv/bin/activate

# Проверяем .env
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден! Создай его из .env.example"
    exit 1
fi

# Запускаем ботов
python3 main.py
