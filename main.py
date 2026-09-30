import logging import os import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters, )
BOT_TOKEN = os.environ["BOT_TOKEN"]
Telegram ID тех, кто обрабатывает +1.
Если пусто — ✅ от любого участника запускает бота.
PROCESSOR_IDS = { int(x) for x in os.getenv("PROCESSOR_IDS", "").replace(" ", "").split(",") if x }
REMINDER_TEXT = ( "⚠️ Не забудьте поставить курьеру смену после оформления.\n" "Если подходящей смены нет, напишите в группу по активации." )
SHIFT_NOT_ASSIGNED_TEXT = ( "❌ Смена не назначена.\n" "Пожалуйста, ребята, свяжитесь с курьером и поставьте ему смену." )
PLUS_ONE = re.compile(r"^\s*+1(?!\d)") CHECK = re.compile(r"^\s*(✅|✔️|☑️)")
logging.basicConfig(level=logging.INFO)
def user_name(user) -> str: return f"@{user.username}" if user.username else user.full_name
async def safe_delete(message): try: await message.delete() except Exception as e: logging.warning("Не удалось удалить сообщение: %s", e)
async def on_check(update: Update, context: ContextTypes.DEFAULT_TYPE): """ Обработчик ответил ✅ на «+1 ...» -> бот отправляет автору +1 сообщение с кнопками. """
msg = update.effective_message
origin = msg.reply_to_message

if not origin:
    return

origin_text = origin.text or origin.caption or ""

if not PLUS_ONE.match(origin_text):
    return

# Если указаны PROCESSOR_IDS — только они могут запускать обработку
if PROCESSOR_IDS and msg.from_user.id not in PROCESSOR_IDS:
    return

# Не дублируем обработку одного и того же +1
done = context.bot_data.setdefault("done", set())
key = (msg.chat_id, origin.message_id)

if key in done:
    return

done.add(key)

# ID автора сообщения +1
uid = origin.from_user.id

keyboard = InlineKeyboardMarkup(
    [[
        InlineKeyboardButton(
            "✅ Назначили",
            callback_data=f"shift:ok:{uid}"
        ),
        InlineKeyboardButton(
            "❌ Не назначили",
            callback_data=f"shift:no:{uid}"
        ),
    ]]
)

# Отправляем автору +1 напоминание
sent = await origin.reply_text(
    REMINDER_TEXT,
    reply_markup=keyboard
)

# Сохраняем исходный текст заявки
context.bot_data.setdefault("origin_text", {})[
    (sent.chat_id, sent.message_id)
] = origin_text
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query
_, action, author_id = query.data.split(":")

# Нажимать может только тот, кто написал +1
if query.from_user.id != int(author_id):
    await query.answer(
        "Эта кнопка не для вас 🙂",
        show_alert=True
    )
    return

await query.answer()

key = (
    query.message.chat_id,
    query.message.message_id
)

origin_text = context.bot_data.get(
    "origin_text", {}
).pop(key, "")

# ==========================================
# ❌ НЕ НАЗНАЧИЛИ
# ==========================================
if action == "no":

    # Отправляем сообщение В ТУ ЖЕ ГРУППУ,
    # где была заявка +1
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=SHIFT_NOT_ASSIGNED_TEXT,
    )

# Удаляем сообщение с кнопками
await safe_delete(query.message)
def main(): app = Application.builder().token(BOT_TOKEN).build()
# Обработка ответа ✅ на +1
app.add_handler(
    MessageHandler(
        filters.ChatType.GROUPS
        & filters.TEXT
        & filters.REPLY
        & filters.Regex(CHECK),
        on_check,
    )
)

# Обработка кнопок
app.add_handler(
    CallbackQueryHandler(
        on_button,
        pattern=r"^shift:"
    )
)

app.run_polling()
if name == "main": main()
