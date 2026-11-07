from apps.audit.models import AuditLog
from apps.bot.models import BotAccount


def record_bot(account: BotAccount, action: str, obj=None, *, target_type: str | None = None, clinic=None) -> None:
    """The bot's counterpart of `apps.audit.services.record`: there is no HTTP request.

    A patient is not a User, so their reads carry no actor; the target and the
    clinic still say whose record was opened.
    """
    AuditLog.objects.create(
        clinic=clinic if clinic is not None else getattr(obj, "clinic", None) or account.clinic,
        actor=account.user if account.kind == BotAccount.Kind.STAFF else None,
        action=action,
        target_type=target_type or (obj._meta.label_lower if obj is not None else "bot.botaccount"),
        target_id=getattr(obj, "pk", None) or account.pk,
    )
