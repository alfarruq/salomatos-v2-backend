"""The bot's conversation, free of Telegram types so it can be tested directly.

`runner.py` turns a Telegram update into a call here and sends the `Reply` back.
Every handler starts from the chat's bound account; nothing the user types can
name another patient, doctor or clinic.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bot import content, texts
from apps.bot.audit import record_bot
from apps.bot.credentials import LoginResult, account_for_chat, authenticate, sign_out
from apps.bot.models import AppointmentReminder, BotAccount
from apps.clinical.pdf import prescription_pdf

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
RX_PREFIX = "rx:"
FILE_LIMIT = 50 * 1024 * 1024


@dataclass
class OutgoingFile:
    name: str
    data: bytes | None = None
    is_photo: bool = False
    # Read when this file is sent, not when the reply is built: a gallery of ten
    # X-rays up to 50 MB each must not sit in memory all at once.
    load: Callable[[], bytes] | None = None

    def read(self) -> bytes:
        return self.data if self.data is not None else self.load()


def _reader(field_file) -> Callable[[], bytes]:
    def read() -> bytes:
        with field_file.open("rb") as handle:
            return handle.read()

    return read


@dataclass
class Out:
    text: str | None = None
    file: OutgoingFile | None = None
    # Inline buttons under this message: (label, callback data).
    buttons: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Reply:
    messages: list[Out] = field(default_factory=list)
    # Reply keyboard to show after the messages; [] removes it, None leaves it.
    keyboard: list[list[str]] | None = None
    # The incoming message held a password and must not stay in the chat.
    delete_incoming: bool = False


def _say(text: str, keyboard=None, **kwargs) -> Reply:
    return Reply(messages=[Out(text=text)], keyboard=keyboard, **kwargs)


def menu_for(account: BotAccount) -> list[list[str]]:
    if account.kind == BotAccount.Kind.PATIENT:
        return [
            [texts.BTN_PRESCRIPTIONS, texts.BTN_GALLERY],
            [texts.BTN_PROCEDURES, texts.BTN_DOCTOR],
            [texts.BTN_LOGOUT],
        ]
    row = []
    if content.doctor_memberships(account.user).exists():
        row.append(texts.BTN_TODAY)
    if content.owned_clinics(account.user).exists():
        row.append(texts.BTN_REPORT)
    return [row, [texts.BTN_LOGOUT]] if row else [[texts.BTN_LOGOUT]]


def handle_start(chat_id: int, state: dict) -> Reply:
    account = account_for_chat(chat_id)
    if account is not None:
        return _say(texts.LOGIN_OK, menu_for(account))
    state.clear()
    state["await"] = "login"
    return _say(texts.WELCOME, [])


def handle_text(chat_id: int, text: str, state: dict) -> Reply:
    text = (text or "").strip()
    account = account_for_chat(chat_id)
    if account is None:
        return _login_step(chat_id, text, state)
    if text == texts.BTN_LOGOUT:
        sign_out(chat_id)
        state.clear()
        state["await"] = "login"
        return _say(texts.LOGGED_OUT, [])
    if account.kind == BotAccount.Kind.PATIENT:
        return _patient(account, text)
    return _staff(account, text)


def handle_callback(chat_id: int, data: str) -> Reply:
    account = account_for_chat(chat_id)
    if account is None:
        return _say(texts.NEED_LOGIN)
    if account.kind == BotAccount.Kind.PATIENT and data.startswith(RX_PREFIX):
        try:
            prescription_id = uuid.UUID(data[len(RX_PREFIX) :])
        except ValueError:
            return Reply()
        prescription = content.patient_prescription(account.patient, prescription_id)
        if prescription is None:
            return Reply()
        record_bot(account, AuditLog.Action.EXPORT, prescription)
        file = OutgoingFile(name=f"retsept-{prescription.pk}.pdf", data=prescription_pdf(prescription))
        return Reply(messages=[Out(file=file)])
    return Reply()


def _login_step(chat_id: int, text: str, state: dict) -> Reply:
    if state.get("await") == "password" and state.get("login"):
        result, account = authenticate(chat_id, state["login"], text)
        state.clear()
        if result == LoginResult.OK:
            record_bot(account, AuditLog.Action.LOGIN, account)
            reply = _say(texts.LOGIN_OK, menu_for(account), delete_incoming=True)
            reply.messages.insert(0, Out(text=texts.PASSWORD_DELETED_NOTE))
            return reply
        state["await"] = "login"
        message = texts.LOGIN_LOCKED if result == LoginResult.LOCKED else texts.LOGIN_INVALID
        return _say(message, delete_incoming=True)
    if not text:
        return _say(texts.NEED_LOGIN)
    state.clear()
    state["await"] = "password"
    state["login"] = text
    return _say(texts.ASK_PASSWORD)


def _patient(account: BotAccount, text: str) -> Reply:
    patient = account.patient
    zone = content.zone_of(patient.clinic)
    if text == texts.BTN_PRESCRIPTIONS:
        items = list(content.patient_prescriptions(patient))
        if not items:
            return _say(texts.NOTHING)
        for item in items:
            record_bot(account, AuditLog.Action.VIEW, item)
        return Reply(
            messages=[Out(text=texts.prescription(item), buttons=[("PDF", f"{RX_PREFIX}{item.pk}")]) for item in items]
        )
    if text == texts.BTN_GALLERY:
        items = list(content.patient_attachments(patient))
        if not items:
            return _say(texts.NOTHING)
        messages = []
        for item in items:
            record_bot(account, AuditLog.Action.EXPORT, item)
            suffix = Path(item.file.name).suffix.lower()
            if item.size_bytes > FILE_LIMIT:
                # Telegram refuses bot uploads over 50 MB; say so instead of reading it into memory.
                messages.append(Out(text=f"{texts.attachment_caption(item)}: {texts.FILE_TOO_BIG}"))
                continue
            file = OutgoingFile(
                name=f"{item.kind}-{item.pk}{suffix}", load=_reader(item.file), is_photo=suffix in PHOTO_SUFFIXES
            )
            messages.append(Out(text=texts.attachment_caption(item), file=file))
        return Reply(messages=messages)
    if text == texts.BTN_PROCEDURES:
        items = list(content.patient_procedures(patient))
        if not items:
            return _say(texts.NOTHING)
        record_bot(account, AuditLog.Action.VIEW, patient, target_type="dental.procedure")
        return _say(texts.procedures(items, zone))
    if text == texts.BTN_DOCTOR:
        member = content.patient_doctor(patient)
        return _say(texts.NO_DOCTOR if member is None else texts.doctor(member))
    return _say(texts.LOGIN_OK, menu_for(account))


def _staff(account: BotAccount, text: str) -> Reply:
    if text == texts.BTN_TODAY:
        doctors = list(content.doctor_memberships(account.user))
        if not doctors:
            return _say(texts.NO_ROLE, menu_for(account))
        messages = []
        for doctor in doctors:
            record_bot(account, AuditLog.Action.VIEW, doctor, target_type="bot.doctor_day")
            messages.append(Out(text=texts.doctor_day(content.doctor_day(doctor))))
        return Reply(messages=messages)
    if text == texts.BTN_REPORT:
        day, rows = content.owner_day(account.user)
        if day is None:
            return _say(texts.NO_ROLE, menu_for(account))
        record_bot(account, AuditLog.Action.VIEW, account, target_type="bot.owner_report", clinic=rows[0].clinic)
        return _say(texts.owner_report(day, rows))
    return _say(texts.LOGIN_OK, menu_for(account))


# Scheduled messages


def morning_messages() -> list[tuple[int, str]]:
    """07:00: each signed-in doctor hears how many visits wait for them today."""
    out = []
    accounts = BotAccount.objects.filter(kind=BotAccount.Kind.STAFF, telegram_chat_id__isnull=False).select_related(
        "user"
    )
    for account in accounts:
        if not account.user.is_active:
            continue
        for doctor in content.doctor_memberships(account.user):
            record_bot(account, AuditLog.Action.VIEW, doctor, target_type="bot.doctor_day")
            out.append((account.telegram_chat_id, texts.doctor_morning(content.doctor_day(doctor))))
    return out


def evening_reports() -> list[tuple[int, str]]:
    """20:00: each signed-in owner gets the day's figures for every branch."""
    out = []
    accounts = BotAccount.objects.filter(kind=BotAccount.Kind.STAFF, telegram_chat_id__isnull=False).select_related(
        "user"
    )
    for account in accounts:
        if not account.user.is_active:
            continue
        day, rows = content.owner_day(account.user)
        if day is None:
            continue
        record_bot(account, AuditLog.Action.VIEW, account, target_type="bot.owner_report", clinic=rows[0].clinic)
        out.append((account.telegram_chat_id, texts.owner_report(day, rows)))
    return out


def appointment_reminders(now: datetime | None = None) -> list[tuple[int, str]]:
    """Patients who linked the bot hear about a visit the evening before and two hours ahead.

    Leads are patients without `registered_at`, so they are covered too. Only
    the chat id and the text leave this function; the sent marker is written first.
    """
    now = now or timezone.now()
    kinds = AppointmentReminder.Kind
    out = []
    for visit, kind in content.reminder_candidates(now):
        _, created = AppointmentReminder.objects.get_or_create(
            appointment=visit, kind=kind, for_start_at=visit.start_at
        )
        if not created:
            continue
        account = visit.patient.bot_account
        record_bot(account, AuditLog.Action.VIEW, visit, target_type="bot.appointment_reminder")
        out.append((account.telegram_chat_id, texts.appointment_reminder(visit, tomorrow=kind == kinds.DAY_BEFORE)))
    return out
