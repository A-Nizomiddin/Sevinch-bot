import csv
import logging
import os
import re
from datetime import datetime

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]  # токен от @BotFather
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # необязательно: куда пересылать комментарии
COMMENTS_FILE = "comments.csv"

REMINDER_TEXT = (
    "Не забудьте поставить курьеру смену после оформления.\n"
    "Если подходящей смены нет, напишите в группу по активации"
)

logging.basicConfig(level=logging.INFO)


def user_name(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


async def on_plus_one(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реагирует на сообщение «+1»."""
    msg = update.effective_message
    uid = msg.from_user.id
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Смена назначена", callback_data=f"shift:ok:{uid}"),
            InlineKeyboardButton("❌ Не назначена", callback_data=f"shift:no:{uid}"),
        ]]
    )
    await msg.reply_text(REMINDER_TEXT, reply_markup=keyboard)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, action, author_id = query.data.split(":")

    # Нажимать может только тот, кто написал «+1»
    if query.from_user.id != int(author_id):
        await query.answer("Эта кнопка не для вас 🙂", show_alert=True)
        return

    await query.answer()
    who = user_name(query.from_user)

    if action == "ok":
        await query.edit_message_text(f"✅ Смена назначена ({who})")
        return

    # Смена не назначена -> просим комментарий (только текст)
    await query.edit_message_text(f"❌ Смена не назначена ({who})")
    origin = query.message.reply_to_message  # исходное «+1»
    prompt = await query.message.chat.send_message(
        f"{who}, напишите комментарий: почему не назначена смена.\n"
        "Ответьте на это сообщение текстом.",
        reply_to_message_id=origin.message_id if origin else query.message.message_id,
        reply_markup=ForceReply(selective=True, input_field_placeholder="Комментарий..."),
    )
    context.bot_data.setdefault("pending", {})[prompt.message_id] = query.from_user.id


async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает комментарий — ответ на сообщение бота."""
    msg = update.effective_message
    pending = context.bot_data.get("pending", {})
    replied = msg.reply_to_message
    if not replied or pending.get(replied.message_id) != msg.from_user.id:
        return
    pending.pop(replied.message_id)

    who = user_name(msg.from_user)
    with open(COMMENTS_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [datetime.now().isoformat(timespec="seconds"), msg.chat.title, who, msg.text]
        )

    await msg.reply_text("Комментарий записан ✅")

    if ADMIN_CHAT_ID:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"Смена не назначена\nГруппа: {msg.chat.title}\nОт: {who}\nКомментарий: {msg.text}",
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    groups = filters.ChatType.GROUPS
    app.add_handler(
        MessageHandler(groups & filters.Regex(re.compile(r"^\s*\+1\s*$")), on_plus_one)
    )
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^shift:"))
    app.add_handler(MessageHandler(groups & filters.TEXT & filters.REPLY & ~filters.COMMAND, on_comment))
    app.run_polling()


if __name__ == "__main__":
    main()
