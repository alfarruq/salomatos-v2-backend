import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


def generate() -> str:
    return secrets.token_urlsafe(9)


def validate_new_password(password: str, user) -> None:
    """Same rules as every other password; raised as a field error on `password`."""
    try:
        validate_password(password, user)
    except DjangoValidationError as err:
        raise serializers.ValidationError({"password": list(err.messages)}, code="password_invalid") from err
