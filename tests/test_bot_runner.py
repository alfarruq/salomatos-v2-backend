"""The Telegram glue, against a fake bot: no network, no token."""

import asyncio
from types import SimpleNamespace

from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.error import BadRequest

from apps.bot import dialog, texts
from apps.bot.runner import _send, on_error


class FakeBot:
    def __init__(self, refuse=()):
        self.sent = []
        self.refuse = set(refuse)

    async def _record(self, kind, **kwargs):
        if kind in self.refuse:
            raise BadRequest("refused")
        self.sent.append((kind, kwargs))

    async def send_message(self, **kwargs):
        await self._record("message", **kwargs)

    async def send_photo(self, **kwargs):
        await self._record("photo", **kwargs)

    async def send_document(self, **kwargs):
        await self._record("document", **kwargs)


class FakeMessage:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


def fake_update(message=None):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=42), message=message)


def run(reply, bot, message=None):
    asyncio.run(_send(fake_update(message), SimpleNamespace(bot=bot), reply))


def photo(name="x.jpg", size=10):
    return dialog.OutgoingFile(name=name, data=b"x" * size, is_photo=True)


def test_password_message_is_deleted_and_keyboard_rides_the_last_message():
    bot, message = FakeBot(), FakeMessage()
    reply = dialog.Reply(
        messages=[dialog.Out(text="a"), dialog.Out(text="b")], keyboard=[["Menu"]], delete_incoming=True
    )
    run(reply, bot, message)
    assert message.deleted
    assert bot.sent[0][1]["reply_markup"] is None
    assert isinstance(bot.sent[1][1]["reply_markup"], ReplyKeyboardMarkup)


def test_empty_keyboard_removes_it():
    bot = FakeBot()
    run(dialog.Reply(messages=[dialog.Out(text="bye")], keyboard=[]), bot)
    assert isinstance(bot.sent[0][1]["reply_markup"], ReplyKeyboardRemove)


def test_inline_buttons_become_callback_buttons():
    bot = FakeBot()
    run(dialog.Reply(messages=[dialog.Out(text="rx", buttons=[("PDF", "rx:1")])]), bot)
    markup = bot.sent[0][1]["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard[0][0].callback_data == "rx:1"


def test_a_refused_photo_is_sent_as_a_document():
    bot = FakeBot(refuse={"photo"})
    run(dialog.Reply(messages=[dialog.Out(text="cap", file=photo())]), bot)
    assert [kind for kind, _ in bot.sent] == ["document"]


def test_a_large_photo_goes_as_a_document():
    bot = FakeBot()
    run(dialog.Reply(messages=[dialog.Out(file=photo(size=11 * 1024 * 1024))]), bot)
    assert [kind for kind, _ in bot.sent] == ["document"]


def test_one_refused_file_does_not_stop_the_rest():
    bot = FakeBot(refuse={"document"})
    pdf = dialog.OutgoingFile(name="a.pdf", data=b"%PDF")
    run(dialog.Reply(messages=[dialog.Out(file=pdf), dialog.Out(text="after")]), bot)
    assert [kw["text"] for kind, kw in bot.sent] == [texts.NOT_DELIVERED, "after"]


def test_errors_answer_with_a_generic_message(caplog):
    from telegram import Update

    bot = FakeBot()
    update = Update(update_id=1)
    update._effective_chat = SimpleNamespace(id=42)
    asyncio.run(on_error(update, SimpleNamespace(bot=bot, error=ValueError("secret-password"))))
    assert bot.sent[0][1]["text"] == texts.SOMETHING_WRONG
    assert "secret-password" not in caplog.text
