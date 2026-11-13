from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.patients.models import Patient

# A lead whose last booking is this far behind is put away.
STALE_AFTER = timedelta(days=10)


@transaction.atomic
def archive_stale_leads(now=None) -> int:
    """Archives leads with no booking in the last ten days and none ahead.

    Archived, not deleted: patients are never deleted (CLAUDE.md), and the
    bookings that point at a lead are kept so no-shows stay countable.
    """
    now = now or timezone.now()
    cutoff = now - STALE_AFTER
    stale = list(
        Patient.objects.filter(registered_at__isnull=True, archived_at__isnull=True, created_at__lt=cutoff)
        .exclude(appointments__end_at__gte=cutoff)
        .values_list("pk", "clinic_id")
    )
    if not stale:
        return 0
    Patient.objects.filter(pk__in=[pk for pk, _ in stale]).update(archived_at=now, updated_at=now)
    AuditLog.objects.bulk_create(
        AuditLog(
            clinic_id=clinic_id,
            actor=None,
            action=AuditLog.Action.ARCHIVE,
            target_type=Patient._meta.label_lower,
            target_id=pk,
        )
        for pk, clinic_id in stale
    )
    return len(stale)
