from apps.saas.models import PlatformEvent


def record(request, action: str, organization=None, obj=None) -> None:
    PlatformEvent.objects.create(
        actor=request.user,
        action=action,
        organization=organization,
        target_type=obj._meta.label_lower if obj is not None else "",
        target_id=getattr(obj, "pk", None),
        ip_address=request.META.get("REMOTE_ADDR"),
    )
