"""What a customer has paid for, derived from the payment ledger.

Paid periods are computed from non-voided payments on every read instead of
being stored, so voiding a payment can never leave a stale "paid until".
"""

from datetime import date

from django.conf import settings
from django.db.models import Max, Sum
from django.utils import timezone

from apps.saas.models import Contract, PlatformPayment


def _live(organization, kind: str):
    return PlatformPayment.objects.filter(organization=organization, kind=kind, voided_at__isnull=True)


def paid_until(organization, kind: str) -> date | None:
    return _live(organization, kind).aggregate(until=Max("covers_until"))["until"]


def paid_total(organization, kind: str):
    return _live(organization, kind).aggregate(total=Sum("amount"))["total"] or 0


def sms_credits(organization) -> int:
    # Sending is not built yet (no SMS provider), so nothing is spent: this is what was bought.
    return _live(organization, PlatformPayment.Kind.SMS).aggregate(total=Sum("sms_credits"))["total"] or 0


def contract_of(organization) -> Contract | None:
    return Contract.objects.filter(organization=organization).first()


def voice_active(organization, today: date | None = None) -> bool:
    contract = contract_of(organization)
    if contract is None or not contract.voice_enabled:
        return False
    until = paid_until(organization, PlatformPayment.Kind.VOICE)
    return until is not None and until >= (today or timezone.localdate())


def voice_limit(organization) -> int:
    contract = contract_of(organization)
    if contract is None or contract.voice_monthly_limit is None:
        return settings.VOICE_MONTHLY_LIMIT
    return contract.voice_monthly_limit
