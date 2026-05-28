# Скрипт установки зависимостей и проверки системы

echo "🚀 Установка системы бронирования переговорных комнат"
echo "=" * 60

# Шаг 1: Создание виртуального окружения
echo "📦 Шаг 1: Создание виртуального окружения..."
python3 -m venv venv
echo "✅ Окружение создано"

# Шаг 2: Активация и установка зависимостей
echo "📦 Шаг 2: Установка зависимостей..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Зависимости установлены"

# Шаг 3: Проверка подключения к Google Sheets
echo "🔍 Шаг 3: Проверка подключения к Google Sheets..."
python3 test_db.py

if [ $? -eq 0 ]; then
    echo "✅ Google Sheets подключен"
else
    echo "❌ Ошибка подключения к Google Sheets"
    echo "   Проверь service_account.json и доступ к таблице"
    exit 1
fi

# Шаг 4: Проверка изображений
echo "🖼️  Шаг 4: Проверка изображений..."
for img in images/coworking.jpg images/big.jpg images/small.jpg; do
    if [ -f "$img" ]; then
        echo "   ✅ $img"
    else
        echo "   ❌ $img не найден"
    fi
done

echo ""
echo "=" * 60
echo "✅ Установка завершена!"
echo ""
echo "📋 Для запуска ботов выполни:"
echo "   source venv/bin/activate"
echo "   python3 main.py"
echo ""
echo "🧪 Для тестирования Google Sheets:"
echo "   source venv/bin/activate"
echo "   python3 test_db.py"
echo "=" * 60
