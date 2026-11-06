import re

from django.core.exceptions import ValidationError

PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")

# FDI two-digit notation: quadrants 1-4 hold 8 permanent teeth each,
# quadrants 5-8 hold 5 primary (milk) teeth each.
PERMANENT_TEETH = frozenset(q * 10 + n for q in range(1, 5) for n in range(1, 9))
PRIMARY_TEETH = frozenset(q * 10 + n for q in range(5, 9) for n in range(1, 6))
FDI_TEETH = PERMANENT_TEETH | PRIMARY_TEETH


def validate_phone(value: str) -> str:
    if not PHONE_RE.match(value):
        raise ValidationError("Enter a valid phone number, e.g. +998901234567.", code="invalid_phone")
    return value


def validate_fdi_tooth(value: int) -> int:
    if value not in FDI_TEETH:
        raise ValidationError("Enter a tooth number in FDI notation (11-48 or 51-85).", code="invalid_tooth")
    return value
