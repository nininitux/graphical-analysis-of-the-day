import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Google Sheets API настройки
SPREADSHEET_ID = "your_google_sheet_id"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDENTIALS_FILE = 'credentials.json'
credentials = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=credentials)

# Временные данные для пользователя
user_data = {}

# Функция получения последней строки
def get_last_row():
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A2:E"
    ).execute()
    rows = result.get('values', [])
    if not rows:
        return {
            "start_time": datetime(2024, 12, 10, 7, 0, 0),
            "end_time": datetime(2024, 12, 10, 8, 0, 0)
        }
    else:
        last_row = rows[-1]
        last_start_time = datetime.strptime(last_row[0], "%d.%m.%Y %H:%M:%S")
        last_end_time = datetime.strptime(last_row[1], "%d.%m.%Y %H:%M:%S")
        return {
            "start_time": last_end_time,
            "end_time": last_end_time + timedelta(hours=1)
        }

# Функция добавления строки в Google Sheets
def add_row_to_sheet(data):
    sheet = service.spreadsheets()
    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [data]}
    ).execute()

# Команда /start
async def start(update: Update, context: CallbackContext):
    user_data[update.effective_user.id] = {}
    await update.message.reply_text("Привет! Напиши активность и категорию (например: Работа, Обучение).")

# Команда /last: получение последней записи
async def last_entry(update: Update, context: CallbackContext):
    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A2:E"
        ).execute()
        rows = result.get('values', [])
        if not rows:
            await update.message.reply_text("Таблица пока пустая.")
            return

        # Берём последнюю строку
        last_row = rows[-1]
        last_time = last_row[1]  # Время конца (колонка B)
        last_activity = last_row[4]  # Активность (колонка E)

        # Отправляем данные пользователю
        await update.message.reply_text(f"Последняя запись:\nВремя: {last_time}\nАктивность: {last_activity}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# Сохранение активности и категории
async def log_activity(update: Update, context: CallbackContext):
    try:
        text = update.message.text.split(", ")
        if len(text) != 2:
            await update.message.reply_text("Неверный формат. Используй: <Активность>, <Категория>")
            return

        # Сохраняем данные
        user_data[update.effective_user.id] = {
            "activity": text[0],
            "category": text[1]
        }

        # Отправляем кнопки для выбора оценки удовольствия
        keyboard = [
            [InlineKeyboardButton(str(i), callback_data=f"pleasure_{i}") for i in range(0, 4)],
            [InlineKeyboardButton(str(i), callback_data=f"pleasure_{i}") for i in range(4, 8)],
            [InlineKeyboardButton(str(i), callback_data=f"pleasure_{i}") for i in range(8, 11)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выбери оценку удовольствия (от 0 до 10):", reply_markup=reply_markup)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# Обработка кнопок
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()  # Сразу отвечаем Telegram, чтобы избежать таймаута

    # Сохраняем выбор
    user_id = update.effective_user.id
    data = query.data

    # Обработка оценки удовольствия
    if data.startswith("pleasure_"):
        pleasure = data.split("_")[1]
        user_data[user_id]['pleasure'] = pleasure

        # Отправляем кнопки для выбора типа дня, уровня сложности и приоритета
        keyboard = [
            [InlineKeyboardButton("Будний день", callback_data="Будний день"), InlineKeyboardButton("Выходной день", callback_data="Выходной день")],
            [InlineKeyboardButton("Лёгкий", callback_data="Лёгкий"), InlineKeyboardButton("Средний", callback_data="Средний"), InlineKeyboardButton("Сложный", callback_data="Сложный")],
            [InlineKeyboardButton("Низкий", callback_data="Низкий"), InlineKeyboardButton("Средний", callback_data="Средний"), InlineKeyboardButton("Высокий", callback_data="Высокий")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выбери тип дня, уровень сложности и приоритет активности:", reply_markup=reply_markup)
        return

    # Обработка остальных параметров
    if "день" in data:
        user_data[user_id]['day_type'] = data
    elif data in ["Лёгкий", "Средний", "Сложный"]:
        user_data[user_id]['difficulty'] = data
    elif data in ["Низкий", "Средний", "Высокий"]:
        user_data[user_id]['priority'] = data

    # Проверяем, заполнены ли все данные
    if all(key in user_data[user_id] for key in ["day_type", "difficulty", "priority", "pleasure"]):
        times = get_last_row()
        start_time = times["start_time"]
        end_time = times["end_time"]

        # Формируем данные
        row_data = [
            start_time.strftime("%d.%m.%Y %H:%M:%S"),
            end_time.strftime("%d.%m.%Y %H:%M:%S"),
            user_data[user_id]['day_type'],
            f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}",
            user_data[user_id]['activity'],
            user_data[user_id]['difficulty'],
            user_data[user_id]['pleasure'],
            user_data[user_id]['priority'],
            user_data[user_id]['category']
        ]

        # Добавляем строку в таблицу
        add_row_to_sheet(row_data)
        await query.edit_message_text("Данные успешно записаны!")

        # Очищаем данные пользователя
        user_data[user_id] = {}

# Глобальный обработчик ошибок
async def error_handler(update: object, context: CallbackContext) -> None:
    logging.error(msg="Ошибка в обработке:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

def main():
    application = Application.builder().token("your_tg_token_bot").build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("last", last_entry))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_activity))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
