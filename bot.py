import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
import aiocron
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# Логирование
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Sheets API настройки
SPREADSHEET_ID = "1h-08KCBUbdnVuqVEcR76E4ZxqgevJUu6CaTshLa3uzs"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDENTIALS_FILE = 'credentials.json'
credentials = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=credentials)

# Временные данные для пользователя
user_data = {}
subscribed_users = set()

# Функция добавления строки в Google Sheets
def add_row_to_sheet(data):
    sheet = service.spreadsheets()
    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [data]}
    ).execute()

# Функция получения последней строки
def get_last_row():
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A2:I"
    ).execute()
    rows = result.get('values', [])
    if not rows:
        return {
            "start_time": datetime.now(),
            "end_time": datetime.now() + timedelta(hours=1)
        }
    else:
        last_row = rows[-1]
        last_end_time = datetime.strptime(last_row[1], "%d.%m.%Y %H:%M:%S")
        return {
            "start_time": last_end_time,
            "end_time": last_end_time + timedelta(hours=1)
        }

# Команда /start
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    subscribed_users.add(user_id)
    user_data[user_id] = {}
    await update.message.reply_text(
        "Привет! Напиши активность и категорию (например: Работа, Обучение). Каждую новую точку часа я буду спрашивать, чем вы занимались."
    )

# Команда /stop для отписки от уведомлений
async def stop(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in subscribed_users:
        subscribed_users.remove(user_id)
        await update.message.reply_text("Вы отписались от уведомлений.")
    else:
        await update.message.reply_text("Вы не были подписаны на уведомления.")

# Команда /last: получение последней записи
async def last_entry(update: Update, context: CallbackContext):
    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A2:I"
        ).execute()
        rows = result.get('values', [])
        if not rows:
            await update.message.reply_text("Таблица пока пустая.")
            return

        last_row = rows[-1]
        last_time = last_row[1]  # Время конца (колонка B)
        last_activity = last_row[4]  # Активность (колонка E)

        await update.message.reply_text(f"Последняя запись:\nВремя: {last_time}\nАктивность: {last_activity}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# Команда /stats: получение статистики за выбранный период
async def stats(update: Update, context: CallbackContext):
    try:
        args = context.args
        if len(args) != 1 or args[0] not in ["day", "week"]:
            await update.message.reply_text("Используй: /stats day или /stats week")
            return

        now = datetime.now()
        if args[0] == "day":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif args[0] == "week":
            start_date = now - timedelta(days=now.weekday())
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A2:I"
        ).execute()
        rows = result.get('values', [])
        if not rows:
            await update.message.reply_text("Таблица пока пустая.")
            return

        stats_data = []
        for row in rows:
            try:
                end_time = datetime.strptime(row[1], "%d.%m.%Y %H:%M:%S")
                if end_time >= start_date:
                    stats_data.append(row)
            except Exception as e:
                logging.error(f"Ошибка обработки строки {row}: {e}")

        if not stats_data:
            await update.message.reply_text(f"Нет данных за выбранный период ({args[0]}).")
            return

        category_time = {}
        total_pleasure = 0
        total_entries = 0
        activity_count = {}

        for row in stats_data:
            category = row[8]  # Категория
            pleasure = int(row[6])  # Оценка удовольствия
            activity = row[4]  # Активность
            start_time = datetime.strptime(row[0], "%d.%m.%Y %H:%M:%S")
            end_time = datetime.strptime(row[1], "%d.%m.%Y %H:%M:%S")
            duration = (end_time - start_time).total_seconds() / 3600

            category_time[category] = category_time.get(category, 0) + duration
            total_pleasure += pleasure
            total_entries += 1
            activity_count[activity] = activity_count.get(activity, 0) + 1

        stats_message = "Статистика за выбранный период:\n"
        stats_message += "Часы по категориям:\n"
        for category, hours in category_time.items():
            stats_message += f"- {category}: {hours:.2f} часов\n"

        if total_entries > 0:
            avg_pleasure = total_pleasure / total_entries
            stats_message += f"\nСредняя оценка удовольствия: {avg_pleasure:.2f}\n"

        most_popular = max(activity_count, key=activity_count.get, default="Нет данных")
        stats_message += f"\nСамая популярная активность: {most_popular}"

        await update.message.reply_text(stats_message)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# Сохранение активности и категории
async def log_activity(update: Update, context: CallbackContext):
    try:
        text = update.message.text.split(", ")
        if len(text) != 2:
            await update.message.reply_text("Неверный формат. Используй: <Активность>, <Категория>")
            return

        user_id = update.effective_user.id
        user_data[user_id] = {
            "activity": text[0],
            "category": text[1]
        }

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
    await query.answer(cache_time=0, text="Обрабатываю ваш выбор...")

    user_id = update.effective_user.id
    data = query.data

    if data.startswith("pleasure_"):
        pleasure = data.split("_")[1]
        user_data[user_id]['pleasure'] = pleasure

        keyboard = [
            [InlineKeyboardButton("Будний день", callback_data="Будний день"), InlineKeyboardButton("Выходной день", callback_data="Выходной день")],
            [InlineKeyboardButton("Лёгкий", callback_data="Лёгкий"), InlineKeyboardButton("Средний", callback_data="Средний"), InlineKeyboardButton("Сложный", callback_data="Сложный")],
            [InlineKeyboardButton("Низкий", callback_data="Низкий"), InlineKeyboardButton("Средний", callback_data="Средний"), InlineKeyboardButton("Высокий", callback_data="Высокий")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выбери тип дня, уровень сложности и приоритет активности:", reply_markup=reply_markup)
        return

    if "день" in data:
        user_data[user_id]['day_type'] = data
    elif data in ["Лёгкий", "Средний", "Сложный"]:
        user_data[user_id]['difficulty'] = data
    elif data in ["Низкий", "Средний", "Высокий"]:
        user_data[user_id]['priority'] = data

    if all(key in user_data[user_id] for key in ["day_type", "difficulty", "priority", "pleasure"]):
        times = get_last_row()
        start_time = times["start_time"]
        end_time = times["end_time"]

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

        add_row_to_sheet(row_data)
        await query.edit_message_text("Данные успешно записаны!")
        user_data[user_id] = {}

# Команда /help для отображения доступных команд
async def help_command(update: Update, context: CallbackContext):
    commands = (
        "/start - Начать использование бота и подписаться на уведомления\n"
        "/stop - Отписаться от уведомлений\n"
        "/last - Показать последнюю запись\n"
        "/stats - Показать статистику. Используй: /stats day или /stats week\n"
        "/help - Показать список доступных команд"
    )
    await update.message.reply_text(f"Доступные команды:\n{commands}")

# Глобальный обработчик ошибок
async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error(msg="Ошибка в обработке:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

# Функция для отправки уведомлений
async def send_hourly_notifications():
    logger.info("Проверка отправки уведомлений")
    for user_id in subscribed_users:
        try:
            message = "Пожалуйста, напишите, чем вы занимались последний час."
            await app.bot.send_message(chat_id=user_id, text=message)
            logger.info(f"Уведомление отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# Планировщик задач (каждый час)
@aiocron.crontab('0 * * * *')
async def hourly_task():
    logger.info("Запуск планировщика ежечасных уведомлений")
    await send_hourly_notifications()

# Основная функция запуска бота
def main():
    global app
    app = Application.builder().token("8099090354:AAECu11jG3vPOZvj3loGMNsUvfVR_sKi3rs").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("last", last_entry))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_activity))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    hourly_task.start()
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
