from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class AuditLog(BaseModel):
    """Who touched which record, and when. Holds ids only: never PHI values.

    Rows are append-only; nothing in the API updates or deletes them.
    """

    class Action(models.TextChoices):
        VIEW = "view", "View"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        ARCHIVE = "archive", "Archive"
        RESTORE = "restore", "Restore"
        EXPORT = "export", "Export"
        LOGIN = "login", "Login"

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    action = models.CharField(max_length=16, choices=Action.choices)
    target_type = models.CharField(max_length=64)
    target_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["clinic", "-created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
