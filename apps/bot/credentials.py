"""Issuing, checking and revealing bot logins."""

import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bot import crypto
from apps.bot.models import BotAccount

# Digits only for the login: patients type it on a phone keypad.
LOGIN_DIGITS = 8
# No 0/O, 1/l/I: the password is read aloud or copied from paper.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PASSWORD_LENGTH = 8
MAX_FAILED_ATTEMPTS = 5
LOCK_FOR = timedelta(minutes=15)


@dataclass(frozen=True)
class Credentials:
    login: str
    password: str | None
    linked: bool


def _new_login() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(LOGIN_DIGITS))


def _new_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))


def _set_password(account: BotAccount) -> None:
    password = _new_password()
    account.password_hash = make_password(password)
    account.password_encrypted = crypto.encrypt(password)


def _create(**fields) -> BotAccount:
    for _ in range(10):
        account = BotAccount(login=_new_login(), **fields)
        _set_password(account)
        try:
            with transaction.atomic():
                account.save()
            return account
        except IntegrityError:
            # A login collision; 10^8 logins make a second one vanishingly rare.
            continue
    raise RuntimeError("Could not allocate a unique bot login.")


def issue_for_patient(patient) -> BotAccount:
    existing = BotAccount.objects.filter(patient=patient).first()
    return existing or _create(kind=BotAccount.Kind.PATIENT, patient=patient, clinic=patient.clinic)


def issue_for_user(user) -> BotAccount:
    existing = BotAccount.objects.filter(user=user).first()
    return existing or _create(kind=BotAccount.Kind.STAFF, user=user)


def reveal(account: BotAccount) -> Credentials:
    return Credentials(
        login=account.login,
        password=crypto.decrypt(account.password_encrypted),
        linked=account.telegram_chat_id is not None,
    )


def reset(account: BotAccount) -> BotAccount:
    """A new password, and the Telegram chat that used the old one is signed out."""
    _set_password(account)
    account.telegram_chat_id = None
    account.linked_at = None
    account.failed_attempts = 0
    account.locked_until = None
    account.save()
    return account


class LoginResult:
    OK = "ok"
    INVALID = "invalid"
    LOCKED = "locked"


def authenticate(chat_id: int, login: str, password: str) -> tuple[str, BotAccount | None]:
    """Checks a login typed into the bot and binds the account to that chat.

    One chat per account and one account per chat: signing in elsewhere signs
    the previous chat out, so a lost phone stops seeing data once the patient
    signs in again or the clinic resets the password.
    """
    now = timezone.now()
    with transaction.atomic():
        # People copy a login with spaces or dashes ("1234 5678"); only the digits matter.
        typed = "".join(ch for ch in login if ch.isdigit())
        account = BotAccount.objects.select_for_update().filter(login=typed).first()
        if account is None:
            return LoginResult.INVALID, None
        if account.locked_until is not None and account.locked_until > now:
            return LoginResult.LOCKED, None
        if not check_password(password.strip(), account.password_hash):
            account.failed_attempts += 1
            if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
                account.failed_attempts = 0
                account.locked_until = now + LOCK_FOR
            account.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
            return LoginResult.INVALID, None
        if not _subject_active(account):
            return LoginResult.INVALID, None
        BotAccount.objects.filter(telegram_chat_id=chat_id).exclude(pk=account.pk).update(
            telegram_chat_id=None, linked_at=None
        )
        account.telegram_chat_id = chat_id
        account.linked_at = now
        account.failed_attempts = 0
        account.locked_until = None
        account.save(update_fields=["telegram_chat_id", "linked_at", "failed_attempts", "locked_until", "updated_at"])
    return LoginResult.OK, account


def _subject_active(account: BotAccount) -> bool:
    clinic = account.clinic
    if clinic is not None and not (clinic.is_active and clinic.organization.is_active):
        return False
    if account.kind == BotAccount.Kind.PATIENT:
        return account.patient.archived_at is None
    return (
        account.user.is_active
        and account.user.memberships.filter(
            is_active=True, clinic__is_active=True, clinic__organization__is_active=True
        ).exists()
    )


def account_for_chat(chat_id: int) -> BotAccount | None:
    account = (
        BotAccount.objects.select_related("patient", "user", "clinic__organization")
        .filter(telegram_chat_id=chat_id)
        .first()
    )
    if account is None or not _subject_active(account):
        return None
    return account


def sign_out(chat_id: int) -> None:
    BotAccount.objects.filter(telegram_chat_id=chat_id).update(telegram_chat_id=None, linked_at=None)
