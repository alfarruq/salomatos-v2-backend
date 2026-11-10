"""Issue and read back the temporary password given to a customer's owner."""

from apps.accounts.models import User
from apps.bot.crypto import decrypt, encrypt
from apps.saas.models import IssuedCredential


def issue(user: User, password: str) -> None:
    """Call after `user.set_password(password)` and a save, so the stored hash matches."""
    IssuedCredential.objects.update_or_create(
        user=user, defaults={"password_encrypted": encrypt(password), "password_hash": user.password}
    )


def current(user: User) -> str | None:
    """The temporary password while it is still the user's password, else None (and the copy is dropped)."""
    credential = IssuedCredential.objects.filter(user=user).first()
    if credential is None:
        return None
    if credential.password_hash != user.password:
        credential.delete()
        return None
    return decrypt(credential.password_encrypted)
