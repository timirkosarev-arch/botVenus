import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, PicklePersistence, filters,
)

TOKEN = "9179485941:AAEMOBSmz0bg74yMweS7cj3awZtqDuLZYek"
CHANNEL = "@venus1ai"
CHANNEL_URL = "https://t.me/venus1ai"
ADMINS = [8189135964, 8897772924]  # 8897772924 - главный админ
APK_URL = "https://github.com/timirkosarev-arch/edit-web-site/releases/download/ai/Venus.Ai_1_1.apk"

logging.basicConfig(level=logging.INFO)

WELCOME = (
    "Venus AI - твой ИИ-помощник\n\n"
    "Чтобы скачать приложение для Android, нужно быть подписанным на наш канал.\n"
    "Нашёл ошибку или есть вопрос? Нажми «Сообщить об ошибке»."
)


def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Скачать для Android", callback_data="download")],
        [InlineKeyboardButton("Сообщить об ошибке", callback_data="report")],
    ])


def back_row():
    return [InlineKeyboardButton("Назад", callback_data="menu")]


async def show(ctx, chat_id, text, kb):
    """Всё общение с пользователем идёт в одном сообщении: редактируем его."""
    mid = ctx.user_data.get("menu_id")
    if mid:
        try:
            await ctx.bot.edit_message_text(text, chat_id=chat_id, message_id=mid, reply_markup=kb)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
    m = await ctx.bot.send_message(chat_id, text, reply_markup=kb)
    ctx.user_data["menu_id"] = m.message_id


async def safe_delete(msg):
    try:
        await msg.delete()
    except Exception:
        pass


async def is_subscribed(bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(CHANNEL, user_id)
        if m.status in ("member", "administrator", "creator"):
            return True
        if m.status == "restricted" and getattr(m, "is_member", False):
            return True
        return False
    except Exception as e:
        logging.warning("Проверка подписки не удалась (бот админ в канале?): %s", e)
        return False


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    old = ctx.user_data.get("menu_id")
    ctx.user_data.clear()
    if old:
        try:
            await ctx.bot.delete_message(chat_id, old)
        except Exception:
            pass
    if update.message:
        await safe_delete(update.message)
    await show(ctx, chat_id, WELCOME, main_kb())


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    chat_id = q.message.chat_id

    # Кнопка «Ответить» у админов (сообщение с жалобой не редактируем)
    if q.data.startswith("reply:"):
        if uid in ADMINS:
            ctx.user_data["reply_to"] = int(q.data.split(":")[1])
            await q.answer("Напишите ответ следующим сообщением. Отмена: /start", show_alert=True)
        else:
            await q.answer()
        return

    # Остальные кнопки работают в том же сообщении
    ctx.user_data["menu_id"] = q.message.message_id

    if q.data == "menu":
        await q.answer()
        ctx.user_data.pop("mode", None)
        await show(ctx, chat_id, WELCOME, main_kb())

    elif q.data == "download":
        if await is_subscribed(ctx.bot, uid):
            await q.answer("Подписка подтверждена")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Скачать Venus AI (APK)", url=APK_URL)],
                back_row(),
            ])
            await show(ctx, chat_id,
                       "Готово! Нажми кнопку, скачай файл и установи.\n"
                       "Если Android попросит, разреши установку из этого источника.", kb)
        else:
            await q.answer("Сначала подпишитесь на канал", show_alert=True)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Подписаться на канал", url=CHANNEL_URL)],
                [InlineKeyboardButton("Я подписался, проверить", callback_data="download")],
                back_row(),
            ])
            await show(ctx, chat_id,
                       "Чтобы скачать приложение, подпишитесь на канал, затем нажмите «Я подписался, проверить».", kb)

    elif q.data == "report":
        await q.answer()
        ctx.user_data["mode"] = "report"
        await show(ctx, chat_id,
                   "Опишите ошибку или вопрос одним сообщением. Можно приложить скриншот.",
                   InlineKeyboardMarkup([back_row()]))
    else:
        await q.answer()


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Админ отвечает пользователю
    if user.id in ADMINS and ctx.user_data.get("reply_to"):
        target = ctx.user_data.pop("reply_to")
        if not msg.text:
            ctx.user_data["reply_to"] = target
            await msg.reply_text("Пока можно отвечать только текстом. Напишите ответ.")
            return
        try:
            await ctx.bot.send_message(target, f"Ответ поддержки Venus AI:\n\n{msg.text}")
            await msg.reply_text("Ответ отправлен.")
            for a in ADMINS:
                if a != user.id:
                    await ctx.bot.send_message(
                        a, f"{user.full_name} ответил пользователю {target}:\n\n{msg.text}")
        except (Forbidden, BadRequest):
            await msg.reply_text("Не удалось отправить: пользователь заблокировал бота или чат недоступен.")
        return

    # Пользователь отправляет ошибку
    if ctx.user_data.get("mode") == "report":
        ctx.user_data.pop("mode", None)
        username = f"@{user.username}" if user.username else "без username"
        header = f"Сообщение об ошибке\nОт: {user.full_name} ({username})\nID: {user.id}\n\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Ответить", callback_data=f"reply:{user.id}")]])
        for a in ADMINS:
            try:
                if msg.photo:
                    await ctx.bot.send_photo(a, msg.photo[-1].file_id,
                                             caption=(header + (msg.caption or ""))[:1024], reply_markup=kb)
                elif msg.text:
                    await ctx.bot.send_message(a, header + msg.text, reply_markup=kb)
                else:
                    await ctx.bot.send_message(a, header + "[вложение не поддерживается]", reply_markup=kb)
            except Exception as e:
                logging.warning("Не удалось отправить админу %s: %s", a, e)
        await safe_delete(msg)
        await show(ctx, chat_id, "Спасибо! Сообщение отправлено, ответим здесь же.", main_kb())
        return

    # Любое другое сообщение: убираем его и показываем меню в том же сообщении
    await safe_delete(msg)
    await show(ctx, chat_id, WELCOME, main_kb())


# Мини-сервер для бесплатного хостинга и UptimeRobot
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def run_health():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()


def main():
    threading.Thread(target=run_health, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).persistence(PicklePersistence("bot_data.pkl")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
