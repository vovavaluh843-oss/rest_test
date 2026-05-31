#!/usr/bin/env bash
#
# run.sh — Скрипт запуска системы бронирования
# Проверяет окружение, зависимости и запускает ботов.
#

set -euo pipefail

# === Цвета для вывода ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/startup.log"

cd "$PROJECT_DIR"

info "Система бронирования переговорных комнат"
info "Рабочая директория: ${PROJECT_DIR}"
echo ""

# === 1. Проверка виртуального окружения ===
info "Проверка виртуального окружения..."

if [ ! -d "venv" ]; then
    warn "Виртуальное окружение не найдено. Создаю..."
    python3 -m venv venv || fail "Не удалось создать venv. Установите python3 и попробуйте снова."
    ok "venv создан"
else
    ok "venv найден"
fi

# Активация venv
source venv/bin/activate || fail "Не удалось активировать venv"
ok "venv активирован: $(python3 --version)"

# === 2. Установка зависимостей ===
info "Проверка зависимостей..."

if [ ! -f "requirements.txt" ]; then
    fail "requirements.txt не найден в ${PROJECT_DIR}"
fi

# Устанавливаем/обновляем зависимости
pip3 install -r requirements.txt --quiet --disable-pip-version-check 2>&1 | tail -1
if [ $? -ne 0 ]; then
    fail "Ошибка установки зависимостей. Проверьте requirements.txt."
fi
ok "Зависимости установлены"

# === 3. Проверка .env файла ===
info "Проверка файла .env..."

if [ ! -f ".env" ]; then
    fail ".env не найден! Скопируйте .env.example и заполните токены:\n  cp .env.example .env\n  nano .env"
fi

# Проверяем, что .env содержит ключевые переменные
source <(grep -v '^#' .env | grep -v '^$' | sed 's/=.*//')

MISSING=0
for VAR in TELEGRAM_BOT_TOKEN VK_BOT_TOKEN GOOGLE_SPREADSHEET_ID; do
    if [ -z "${!VAR:-}" ]; then
        warn "Переменная ${VAR} не задана в .env"
        MISSING=$((MISSING + 1))
    fi
done

if [ $MISSING -gt 0 ]; then
    fail "Заполните все обязательные переменные в .env (${MISSING} отсутствуют)"
fi
ok ".env проверен, все обязательные переменные заданы"

# === 4. Проверка сервисного аккаунта Google ===
info "Проверка Google Service Account..."

SA_PATH="${PROJECT_DIR}/data/service_account.json"
if [ ! -f "$SA_PATH" ]; then
    warn "service_account.json не найден в data/"
    warn "Создайте сервисный аккаунт Google Cloud и скачайте JSON-ключ"
    warn "Инструкция: https://docs.gspread.org/en/latest/oauth2.html"
    fail "Без сервисного аккаунта бот не сможет подключиться к Google Sheets"
fi
ok "service_account.json найден"

# === 5. Проверка папки для логов ===
mkdir -p "$LOG_DIR"
ok "Папка логов: ${LOG_DIR}"

# === 6. Проверка фотографий комнат ===
info "Проверка изображений комнат..."

IMAGES_DIR="${PROJECT_DIR}/images"
MISSING_IMAGES=0
for IMG in coworking.jpg big.jpg small.jpg; do
    if [ ! -f "${IMAGES_DIR}/${IMG}" ]; then
        warn "Изображение не найдено: images/${IMG}"
        MISSING_IMAGES=$((MISSING_IMAGES + 1))
    fi
done

if [ $MISSING_IMAGES -gt 0 ]; then
    warn "Отсутствуют ${MISSING_IMAGES} изображений. Бот будет работать, но без фото комнат."
else
    ok "Все изображения на месте"
fi

# === 7. Запуск ===
echo ""
info "Запуск системы бронирования..."
info "Логи пишутся в: ${LOG_FILE}"
echo "============================================================"

python3 main.py 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    ok "Система остановлена корректно (код ${EXIT_CODE})"
else
    warn "Система остановлена с кодом ${EXIT_CODE}"
    info "Проверьте логи: tail -100 ${LOG_FILE}"
fi

exit $EXIT_CODE
