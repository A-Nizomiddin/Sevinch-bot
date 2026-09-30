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

REMINDER_TEXT = (
    "Не забудьте выбрать смену курьеру.\n"
    "Если подходящей смены нет — напишите в группу, ребята поставят"
)

# Сообщение должно НАЧИНАТЬСЯ с +1 (дальше может быть любой текст: "+1 Tezkor", "+1Love"...)
# Исключение: "+10", "+123..." (после +1 сразу цифра) — не считается.
PLUS_ONE = re.compile(r"^\s*\+1(?!\d)")

logging.basicConfig(level=logging.INFO)


def user_name(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


async def safe_delete(message):
    try:
        await message.delete()
    except Exception as e:
        logging.warning("Не удалось удалить сообщение: %s", e)


async def on_plus_one(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = msg.from_user.id
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Назначили", callback_data=f"shift:ok:{uid}"),
            InlineKeyboardButton("❌ Не назначили", callback_data=f"shift:no:{uid}"),
        ]]
    )
    await msg.reply_text(REMINDER_TEXT, reply_markup=keyboard)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, action, author_id = query.data.split(":")

    # Нажимать может только тот, кто написал +1
    if query.from_user.id != int(author_id):
        await query.answer("Эта кнопка не для вас 🙂", show_alert=True)
        return

    await query.answer()

    if action == "no" and ADMIN_CHAT_ID:
        origin = query.message.reply_to_message
        text = origin.text if origin and origin.text else ""
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"❌ Смена не назначена\nГруппа: {query.message.chat.title}\n"
            f"От: {user_name(query.from_user)}\nСообщение: {text}",
        )

    # В обоих случаях убираем сообщение бота, чтобы не спамить
    await safe_delete(query.message)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & filters.Regex(PLUS_ONE),
            on_plus_one,
        )
    )
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^shift:"))
    app.run_polling()


if __name__ == "__main__":
    main()
