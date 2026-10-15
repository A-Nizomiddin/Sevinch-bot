import io
import logging
import os
import re
import uuid
from datetime import datetime

import couriers
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Telegram ID тех, кто обрабатывает +1 / +2 / +3.
# Если пусто — ✅ от любого участника запускает бота.
PROCESSOR_IDS = {
    int(x)
    for x in os.getenv("PROCESSOR_IDS", "").replace(" ", "").split(",")
    if x
}

# Кто может загружать файл «курьеры без договора» (Telegram ID через запятую). Пусто = никто.
UPLOAD_IDS = {
    int(x)
    for x in os.getenv("UPLOAD_IDS", "").replace(" ", "").split(",")
    if x
}
# {"NOVA-DRIVE": -100..., ...} из переменной LP_GROUPS
LP_GROUPS = couriers.load_lp_groups()

REMINDER_TEXT = (
    "⚠️ После оформления курьера не забудьте помочь ему выбрать подходящую смену."
)

# Исходное сообщение может начинаться с +1, +2 или +3.
PLUS_ONE = re.compile(r"^\s*\+(?:1|2|3)(?!\d)")

# Ответ обработчика: ✅ / ✔️ / ☑️
CHECK = re.compile(r"^\s*(?:✅|✔️|☑️)")

logging.basicConfig(level=logging.INFO)


def user_name(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


async def safe_delete(message):
    try:
        await message.delete()
    except Exception as e:
        logging.warning("Не удалось удалить сообщение: %s", e)


async def on_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик отвечает ✅ на сообщение +1 / +2 / +3.
    Бот отвечает автору сообщения и напоминает про выбор смены.
    """

    msg = update.effective_message

    if not msg:
        return

    origin = msg.reply_to_message

    if not origin:
        return

    origin_text = origin.text or origin.caption or ""

    # Проверяем +1, +2 или +3.
    if not PLUS_ONE.match(origin_text):
        return

    # Если указаны PROCESSOR_IDS — проверяем отправителя ✅.
    if PROCESSOR_IDS and msg.from_user.id not in PROCESSOR_IDS:
        return

    # Не дублируем сообщение, если несколько раз поставили ✅.
    done = context.bot_data.setdefault("done", set())

    key = (msg.chat_id, origin.message_id)

    if key in done:
        return

    done.add(key)

    # ID автора +1 / +2 / +3.
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

    # Отправляем сообщение в ответ на +1 / +2 / +3.
    sent = await origin.reply_text(
        REMINDER_TEXT,
        reply_markup=keyboard,
    )

    # Сохраняем исходную заявку.
    context.bot_data.setdefault("origin_text", {})[
        (sent.chat_id, sent.message_id)
    ] = origin_text


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    _, action, author_id = query.data.split(":")

    # Нажимать может только тот, кто написал +1 / +2 / +3.
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

    # Если нажали "Не назначили".
    if action == "no" and ADMIN_CHAT_ID:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"❌ Пожалуйста, ребята, свяжитесь с курьером "
            f"и помогите ему выбрать подходящую смену.\n"
            f"Группа: {query.message.chat.title}\n"
            f"От: {user_name(query.from_user)}\n"
            f"Заявка: {origin_text}",
        )

    # Удаляем сообщение бота.
    await safe_delete(query.message)


# ───────────── Рассылка файла «курьеры без договора» по группам ЛП ─────────────

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ присылает боту в личку csv/zip -> бот делит по ЛП и просит подтвердить отправку."""
    msg = update.effective_message
    if msg.from_user.id not in UPLOAD_IDS:
        return
    doc = msg.document
    name = doc.file_name or ""
    if not name.lower().endswith((".csv", ".zip")):
        await msg.reply_text("Пришлите файл .csv или .zip со списком курьеров.")
        return

    tg_file = await doc.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    try:
        header, rows = couriers.read_rows(name, data)
        parts = couriers.split_by_lp(header, rows)
    except Exception as e:
        await msg.reply_text(f"Не удалось разобрать файл: {e}")
        return

    token = uuid.uuid4().hex[:8]
    context.bot_data.setdefault("batches", {})[token] = parts

    lines, missing = [], []
    for lp, (_, n, _) in parts.items():
        if couriers.lookup_group(lp, LP_GROUPS) is None:
            missing.append(lp)
            lines.append(f"⚠️ {lp}: {n} (группа не задана)")
        else:
            lines.append(f"✅ {lp}: {n}")
    text = f"Всего курьеров: {len(rows)}, ЛП: {len(parts)}\n\n" + "\n".join(lines)
    if missing:
        text += "\n\nДля ⚠️ ЛП файл не уйдёт: добавьте их группы в переменную LP_GROUPS."
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("📤 Отправить в группы", callback_data=f"lp:send:{token}"),
            InlineKeyboardButton("Отмена", callback_data=f"lp:cancel:{token}"),
        ]]
    )
    await msg.reply_text(text, reply_markup=kb)


async def on_lp_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in UPLOAD_IDS:
        await query.answer("Нет доступа", show_alert=True)
        return
    _, action, token = query.data.split(":")
    parts = context.bot_data.get("batches", {}).pop(token, None)
    if parts is None:
        await query.answer("Список устарел, пришлите файл заново", show_alert=True)
        return
    await query.answer()

    if action == "cancel":
        await query.edit_message_text("Отменено.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    report = []
    for lp, (blob, n, reasons) in parts.items():
        chat_id = couriers.lookup_group(lp, LP_GROUPS)
        if chat_id is None:
            report.append(f"⚠️ {lp}: пропущен, группа не задана")
            continue
        caption = f"{lp}: курьеры без подписанного договора — {n}\n" + "\n".join(
            f"{r}: {c}" for r, c in sorted(reasons.items())
        )
        try:
            await context.bot.send_document(
                chat_id,
                document=io.BytesIO(blob),
                filename=f"{lp}_{today}.csv",
                caption=caption,
            )
            report.append(f"✅ {lp}: отправлено ({n})")
        except Exception as e:
            logging.warning("Не отправлено %s: %s", lp, e)
            report.append(f"❌ {lp}: ошибка отправки ({e})")
    await query.edit_message_text("Готово:\n" + "\n".join(report))


async def on_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/chatid — показывает ID группы, чтобы прописать её в LP_GROUPS (только для UPLOAD_IDS)."""
    msg = update.effective_message
    if msg.from_user.id in UPLOAD_IDS:
        await msg.reply_text(f"ID этого чата: {msg.chat_id}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

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

    # Рассылка файла по ЛП (отдельная логика)
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, on_file)
    )
    app.add_handler(CallbackQueryHandler(on_lp_button, pattern=r"^lp:"))
    app.add_handler(CommandHandler("chatid", on_chatid))

    app.run_polling()


if __name__ == "__main__":
    main()
