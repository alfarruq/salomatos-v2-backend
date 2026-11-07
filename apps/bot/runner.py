"""Telegram glue: long polling, so the bot needs no public URL or webhook endpoint.

Handlers only translate between Telegram and `apps.bot.dialog`, which runs the
ORM in a worker thread via `sync_to_async`.
"""

import logging
from datetime import time
from zoneinfo import ZoneInfo

from asgiref.sync import sync_to_async
from django.conf import settings
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from apps.bot import dialog

logger = logging.getLogger(__name__)

MORNING = time(7, 0)
EVENING = time(20, 0)


def _keyboard(rows):
    if rows is None:
        return None
    if not rows:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def _send(update: Update, context: ContextTypes.DEFAULT_TYPE, reply: dialog.Reply) -> None:
    chat_id = update.effective_chat.id
    if reply.delete_incoming and update.message is not None:
        try:
            await update.message.delete()
        except TelegramError:
            # Deleting can fail (message too old); the login still goes ahead.
            logger.warning("Could not delete a password message.")
    last = len(reply.messages) - 1
    for index, out in enumerate(reply.messages):
        markup = None
        if out.buttons:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(label, callback_data=data)] for label, data in out.buttons]
            )
        elif index == last:
            markup = _keyboard(reply.keyboard)
        if out.file is not None:
            send = context.bot.send_photo if out.file.is_photo else context.bot.send_document
            kwargs = (
                {"photo": out.file.data}
                if out.file.is_photo
                else {"document": out.file.data, "filename": out.file.name}
            )
            await send(chat_id=chat_id, caption=out.text, reply_markup=markup, **kwargs)
        elif out.text:
            await context.bot.send_message(chat_id=chat_id, text=out.text, reply_markup=markup)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply = await sync_to_async(dialog.handle_start)(update.effective_chat.id, context.chat_data)
    await _send(update, context, reply)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply = await sync_to_async(dialog.handle_text)(update.effective_chat.id, update.message.text, context.chat_data)
    await _send(update, context, reply)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    reply = await sync_to_async(dialog.handle_callback)(update.effective_chat.id, update.callback_query.data or "")
    await _send(update, context, reply)


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, build) -> None:
    for chat_id, text in await sync_to_async(build)():
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except TelegramError:
            # One blocked chat must not stop everyone else's message. No chat id in
            # the log line: it identifies a person.
            logger.warning("A scheduled bot message was not delivered.")


async def morning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _broadcast(context, dialog.morning_messages)


async def evening_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _broadcast(context, dialog.evening_reports)


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    # Private chats only: in a group, other members would read a patient's data.
    private = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", on_start, filters=private))
    application.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_callback))
    zone = ZoneInfo(settings.TIME_ZONE)
    application.job_queue.run_daily(morning_job, time=MORNING.replace(tzinfo=zone), name="doctor-morning")
    application.job_queue.run_daily(evening_job, time=EVENING.replace(tzinfo=zone), name="owner-evening")
    return application


def run() -> None:
    build_application(settings.TELEGRAM_BOT_TOKEN).run_polling(allowed_updates=Update.ALL_TYPES)
