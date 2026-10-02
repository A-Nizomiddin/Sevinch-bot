import logging import os import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters, )
BOT_TOKEN = os.environ["BOT_TOKEN"] ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
Telegram ID тех, кто обрабатывает +1 / +2 / +3
Если пусто — ✅ от любого участника запускает бота.
PROCESSOR_IDS = { int(x) for x in os.getenv("PROCESSOR_IDS", "").replace(" ", "").split(",") if x }
REMINDER_TEXT = ( "⚠️ После оформления курьера не забудьте помочь ему выбрать подходящую смену." )
Исходное сообщение может начинаться с:
+1
+2
+3
PLUS_ONE = re.compile(r"^\s*+(?:1|2|3)(?!\d)")
Ответ обработчика:
✅ / ✔️ / ☑️
CHECK = re.compile(r"^\s*(?:✅|✔️|☑️)")
logging.basicConfig(level=logging.INFO)
def user_name(user) -> str: return f"@{user.username}" if user.username else user.full_name
async def safe_delete(message): try: await message.delete() except Exception as e: logging.warning("Не удалось удалить сообщение: %s", e)
async def on_check(update: Update, context: ContextTypes.DEFAULT_TYPE): """ Обработчик отвечает ✅ на сообщение +1 / +2 / +3. Бот отвечает автору сообщения и напоминает про выбор смены. """
msg = update.effective_message

if not msg:
    return

origin = msg.reply_to_message

if not origin:
    return

origin_text = origin.text or origin.caption or ""

# Проверяем +1, +2 или +3
if not PLUS_ONE.match(origin_text):
    return

# Если указаны PROCESSOR_IDS — проверяем отправителя ✅
if PROCESSOR_IDS and msg.from_user.id not in PROCESSOR_IDS:
    return

# Не дублируем сообщение, если несколько раз поставили ✅
done = context.bot_data.setdefault("done", set())

key = (msg.chat_id, origin.message_id)

if key in done:
    return

done.add(key)

# ID автора +1 / +2 / +3
uid = origin.from_user.id

keyboard = InlineKeyboardMarkup(
    [[
        InlineKeyboardButton(
            "✅ Назначили",
            callback_data=f"shift:ok:{uid}",
        ),
        InlineKeyboardButton(
            "❌ Не назначили",
            callback_data=f"shift:no:{uid}",
        ),
    ]]
)

# Отправляем сообщение в ответ на +1 / +2 / +3
sent = await origin.reply_text(
    REMINDER_TEXT,
    reply_markup=keyboard,
)

# Сохраняем исходную заявку
context.bot_data.setdefault("origin_text", {})[
    (sent.chat_id, sent.message_id)
] = origin_text
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query
if not query:
    return

_, action, author_id = query.data.split(":")

# Нажимать может только тот, кто написал +1 / +2 / +3
if query.from_user.id != int(author_id):
    await query.answer(
        "Эта кнопка не для вас 🙂",
        show_alert=True,
    )
    return

await query.answer()

key = (
    query.message.chat_id,
    query.message.message_id,
)

origin_text = context.bot_data.get(
    "origin_text",
    {}
).pop(key, "")

# Если нажали "Не назначили"
if action == "no" and ADMIN_CHAT_ID:
    await context.bot.send_message(
        ADMIN_CHAT_ID,
        f"❌ Пожалуйста, ребята, свяжитесь с курьером "
        f"и помогите ему выбрать подходящую смену.\n"
        f"Группа: {query.message.chat.title}\n"
        f"От: {user_name(query.from_user)}\n"
        f"Заявка: {origin_text}",
    )

# Удаляем сообщение бота
await safe_delete(query.message)
def main(): app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(
    MessageHandler(
        filters.ChatType.GROUPS
        & filters.TEXT
        & filters.REPLY
        & filters.Regex(CHECK),
        on_check,
    )
)

app.add_handler(
    CallbackQueryHandler(
        on_button,
        pattern=r"^shift:",
    )
)

app.run_polling()
if name == "main": main()
