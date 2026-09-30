import logging
import os
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # необязательно: уведомлять о «Не назначили»
# Необязательно: Telegram ID тех, кто обрабатывает +1 (через запятую).
# Если пусто — ✅ от любого участника запускает бота.
PROCESSOR_IDS = {int(x) for x in os.getenv("PROCESSOR_IDS", "").replace(" ", "").split(",") if x}

REMINDER_TEXT = (
    "Не забудьте поставить курьеру смену после оформления.\n"
    "Если подходящей смены нет, напишите в группу по активации"
)

PLUS_ONE = re.compile(r"^\s*\+1(?!\d)")          # исходное сообщение: +1 ...
CHECK = re.compile(r"^\s*(✅|✔️|✔️|☑️|☑️)")          # ответ обработчика: ✅

logging.basicConfig(level=logging.INFO)


def user_name(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


async def safe_delete(message):
    try:
        await message.delete()
    except Exception as e:
        logging.warning("Не удалось удалить сообщение: %s", e)


async def on_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ответил ✅ на «+1 ...» -> бот отвечает автору +1 и напоминает про смену."""
    msg = update.effective_message
    origin = msg.reply_to_message
    if not origin:
        return
    origin_text = origin.text or origin.caption or ""
    if not PLUS_ONE.match(origin_text):
        return
    if PROCESSOR_IDS and msg.from_user.id not in PROCESSOR_IDS:
        return

    # Не дублируем, если ✅ поставили несколько раз на один и тот же +1
    done = context.bot_data.setdefault("done", set())
    key = (msg.chat_id, origin.message_id)
    if key in done:
        return
    done.add(key)

    uid = origin.from_user.id  # кнопки для того, кто написал +1
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Назначили", callback_data=f"shift:ok:{uid}"),
            InlineKeyboardButton("❌ Не назначили", callback_data=f"shift:no:{uid}"),
        ]]
    )
    sent = await origin.reply_text(REMINDER_TEXT, reply_markup=keyboard)  # ответ автору +1
    context.bot_data.setdefault("origin_text", {})[(sent.chat_id, sent.message_id)] = origin_text


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, action, author_id = query.data.split(":")

    # Нажимать может только тот, кто написал +1
    if query.from_user.id != int(author_id):
        await query.answer("Эта кнопка не для вас 🙂", show_alert=True)
        return

    await query.answer()

    key = (query.message.chat_id, query.message.message_id)
    origin_text = context.bot_data.get("origin_text", {}).pop(key, "")

    if action == "no" and ADMIN_CHAT_ID:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"❌ Пожалуйста, ребята, свяжитесь с курьером и поставьте ему смену\nГруппа: {query.message.chat.title}\n"
            f"От: {user_name(query.from_user)}\nЗаявка: {origin_text}",
        )

    await safe_delete(query.message)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & filters.REPLY & filters.Regex(CHECK),
            on_check,
        )
    )
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^shift:"))
    app.run_polling()


if __name__ == "__main__":
    main()
