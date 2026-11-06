import uuid
from pathlib import Path

from django.core.validators import FileExtensionValidator
from django.db import models

from apps.core.models import BaseModel
from apps.core.validators import validate_fdi_tooth

ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "pdf", "dcm"]


def attachment_path(instance, filename: str) -> str:
    # Random name: the original file name often contains the patient's name.
    suffix = Path(filename).suffix.lower()
    return f"clinics/{instance.clinic_id}/attachments/{uuid.uuid4().hex}{suffix}"


class Attachment(BaseModel):
    """X-ray, panorama, CBCT export or intraoral photo.

    Files are never served from a public URL; they are streamed by
    `AttachmentViewSet.download` after the tenant and permission checks.
    """

    class Kind(models.TextChoices):
        XRAY = "xray", "X-ray"
        PANORAMA = "panorama", "Panoramic X-ray"
        CBCT = "cbct", "CBCT"
        PHOTO = "photo", "Photo"
        DOCUMENT = "document", "Document"

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="attachments")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="attachments")
    uploaded_by = models.ForeignKey("tenancy.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    tooth = models.PositiveSmallIntegerField(null=True, blank=True, validators=[validate_fdi_tooth])
    file = models.FileField(upload_to=attachment_path, validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)])
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    taken_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Attachment {self.pk}"
