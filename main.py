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

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # необязательно: куда пересылать причины
LOG_FILE = "comments.csv"

REMINDER_TEXT = (
    "Не забудьте поставить курьеру смену после оформления.\n"
    "Если подходящей смены нет, напишите в группу по активации"
)

# Быстрые причины (кнопки). Можно менять/добавлять.
REASONS = {
    "r1": "Нет подходящей смены",
    "r2": "Курьер не выходит на связь",
    "r3": "Нет доступа к назначению смен",
}

logging.basicConfig(level=logging.INFO)


def user_name(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


async def safe_delete(message):
    try:
        await message.delete()
    except Exception as e:  # нет прав / уже удалено
        logging.warning("Не удалось удалить сообщение: %s", e)


async def record(context, chat, who, text):
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [datetime.now().isoformat(timespec="seconds"), chat.title, who, text]
        )
    if ADMIN_CHAT_ID:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"❌ Смена не назначена\nГруппа: {chat.title}\nОт: {who}\nПричина: {text}",
        )


async def on_plus_one(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if query.from_user.id != int(author_id):
        await query.answer("Эта кнопка не для вас 🙂", show_alert=True)
        return

    await query.answer()
    who = user_name(query.from_user)

    # ✅ Смена назначена -> просто удаляем сообщение бота
    if action == "ok":
        await safe_delete(query.message)
        return

    # ❌ Не назначена -> выбор причины
    if action == "no":
        rows = [
            [InlineKeyboardButton(text, callback_data=f"shift:{key}:{author_id}")]
            for key, text in REASONS.items()
        ]
        rows.append([InlineKeyboardButton("✍️ Другое (написать)", callback_data=f"shift:other:{author_id}")])
        await query.edit_message_text(
            f"{who}, укажите причину, почему смена не назначена:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    # Быстрая причина -> записываем и убираем сообщение
    if action in REASONS:
        await record(context, query.message.chat, who, REASONS[action])
        await safe_delete(query.message)
        return

    # ✍️ Другое -> просим комментарий (только текст)
    if action == "other":
        origin = query.message.reply_to_message
        prompt = await query.message.chat.send_message(
            f"{who}, напишите комментарий ответом на это сообщение.",
            reply_to_message_id=origin.message_id if origin else query.message.message_id,
            reply_markup=ForceReply(selective=True, input_field_placeholder="Комментарий..."),
        )
        context.bot_data.setdefault("pending", {})[prompt.message_id] = {
            "uid": query.from_user.id,
            "reason_msg": query.message,
        }


async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    pending = context.bot_data.get("pending", {})
    replied = msg.reply_to_message
    data = pending.get(replied.message_id) if replied else None
    if not data or data["uid"] != msg.from_user.id:
        return
    pending.pop(replied.message_id)

    await record(context, msg.chat, user_name(msg.from_user), msg.text)
    # чистим сообщения бота, комментарий пользователя остаётся в группе
    await safe_delete(replied)
    await safe_delete(data["reason_msg"])


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    groups = filters.ChatType.GROUPS
    app.add_handler(MessageHandler(groups & filters.Regex(re.compile(r"^\s*\+1\s*$")), on_plus_one))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^shift:"))
    app.add_handler(MessageHandler(groups & filters.TEXT & filters.REPLY & ~filters.COMMAND, on_comment))
    app.run_polling()


if __name__ == "__main__":
    main()
