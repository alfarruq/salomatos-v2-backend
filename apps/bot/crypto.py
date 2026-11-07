"""Reversible encryption for bot passwords, so staff can read one back.

The key comes from BOT_CREDENTIAL_KEY. Without it, a key is derived from
SECRET_KEY so local development works; production sets its own key, because
rotating SECRET_KEY would otherwise make every stored password unreadable.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    key = settings.BOT_CREDENTIAL_KEY
    if not key:
        digest = hashlib.sha256(f"bot-credentials:{settings.SECRET_KEY}".encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # The key changed since this was stored; the caller offers a reset instead.
        return None
