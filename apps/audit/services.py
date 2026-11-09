from apps.audit.models import AuditLog


def record(request, action: str, obj=None, *, target_type: str | None = None, clinic=None) -> None:
    AuditLog.objects.create(
        clinic=clinic if clinic is not None else (getattr(request, "clinic", None) or _clinic_of(obj)),
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        target_type=target_type or (obj._meta.label_lower if obj is not None else ""),
        target_id=getattr(obj, "pk", None),
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _clinic_of(obj):
    from apps.tenancy.models import Clinic

    if isinstance(obj, Clinic):
        return obj
    return getattr(obj, "clinic", None)


def record_many(request, action: str, objects) -> None:
    """One row per object, for list pages: "who saw this patient" must cover lists too."""
    AuditLog.objects.bulk_create(
        AuditLog(
            clinic=getattr(request, "clinic", None) or _clinic_of(obj),
            actor=request.user if request.user.is_authenticated else None,
            action=action,
            target_type=obj._meta.label_lower,
            target_id=obj.pk,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        for obj in objects
    )
