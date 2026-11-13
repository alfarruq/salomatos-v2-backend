"""Telegram glue: long polling, so the bot needs no public URL or webhook endpoint.

Handlers only translate between Telegram and `apps.bot.dialog`, which runs the
ORM in a worker thread via `sync_to_async`.
"""

import logging
from datetime import time
from zoneinfo import ZoneInfo

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from apps.bot import dialog, texts

logger = logging.getLogger(__name__)

MORNING = time(7, 0)
EVENING = time(20, 0)
# The job is idempotent (sent markers), so a short period only bounds how late a reminder can be.
REMINDER_EVERY = 600
# Bot API upload limits: photos 10 MB, other files 50 MB.
PHOTO_LIMIT = 10 * 1024 * 1024


def _keyboard(rows):
    if rows is None:
        return None
    if not rows:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _with_fresh_connection(function):
    """A request/response cycle for the bot: Django only recycles DB connections around
    HTTP requests, so a process that runs for weeks would otherwise keep a connection
    the database dropped long ago and fail on every message after a Postgres restart."""

    def run(*args, **kwargs):
        close_old_connections()
        try:
            return function(*args, **kwargs)
        finally:
            close_old_connections()

    return sync_to_async(run)


async def _send_one(bot, chat_id: int, out: dialog.Out, markup) -> None:
    file = out.file
    if file is None:
        if out.text:
            await bot.send_message(chat_id=chat_id, text=out.text, reply_markup=markup)
        return
    data = await sync_to_async(file.read)()
    if file.is_photo and len(data) <= PHOTO_LIMIT:
        try:
            await bot.send_photo(chat_id=chat_id, photo=data, caption=out.text, reply_markup=markup)
            return
        except TelegramError:
            # Telegram rejects some images as photos (size, ratio); a document always works.
            pass
    await bot.send_document(chat_id=chat_id, document=data, filename=file.name, caption=out.text, reply_markup=markup)


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
        try:
            await _send_one(context.bot, chat_id, out, markup)
        except TelegramError as error:
            # One file Telegram refuses must not hide the rest of the gallery.
            logger.warning("A bot message was not delivered: %s", type(error).__name__)
            await context.bot.send_message(chat_id=chat_id, text=texts.NOT_DELIVERED)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply = await _with_fresh_connection(dialog.handle_start)(update.effective_chat.id, context.chat_data)
    await _send(update, context, reply)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply = await _with_fresh_connection(dialog.handle_text)(
        update.effective_chat.id, update.message.text, context.chat_data
    )
    await _send(update, context, reply)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    reply = await _with_fresh_connection(dialog.handle_callback)(
        update.effective_chat.id, update.callback_query.data or ""
    )
    await _send(update, context, reply)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # The type only: an exception's text or the update can hold a password or a name.
    logger.error("Bot handler failed: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_chat is not None:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=texts.SOMETHING_WRONG)
        except TelegramError:
            pass


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, build) -> None:
    for chat_id, text in await _with_fresh_connection(build)():
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


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _broadcast(context, dialog.appointment_reminders)


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    # Private chats only: in a group, other members would read a patient's data.
    private = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", on_start, filters=private))
    application.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_error_handler(on_error)
    zone = ZoneInfo(settings.TIME_ZONE)
    application.job_queue.run_daily(morning_job, time=MORNING.replace(tzinfo=zone), name="doctor-morning")
    application.job_queue.run_daily(evening_job, time=EVENING.replace(tzinfo=zone), name="owner-evening")
    application.job_queue.run_repeating(reminder_job, interval=REMINDER_EVERY, first=60, name="patient-reminders")
    return application


def run() -> None:
    build_application(settings.TELEGRAM_BOT_TOKEN).run_polling(allowed_updates=Update.ALL_TYPES)
