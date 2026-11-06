from django.db import models

from apps.core.models import BaseModel
from apps.core.validators import validate_phone


class Patient(BaseModel):
    """A clinic's patient record. Not a login: patients reach their data only via the Telegram bot.

    Patients are archived, never deleted, because the medical record has to
    outlive the relationship with the clinic. Clinical rows point here with
    PROTECT for the same reason.
    """

    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="patients")
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=16, validators=[validate_phone])
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=8, choices=Gender.choices, blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    primary_doctor = models.ForeignKey(
        "tenancy.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_patients",
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["clinic", "full_name"]),
            models.Index(fields=["clinic", "phone_number"]),
        ]

    def __str__(self):
        # Kept free of PHI: __str__ ends up in logs and error reports.
        return f"Patient {self.pk}"


class MedicalHistory(BaseModel):
    """Anamnesis the dentist must see before treatment (allergies above all)."""

    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="medical_history")
    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="+")
    allergies = models.TextField(blank=True)
    chronic_conditions = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)
    is_pregnant = models.BooleanField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"MedicalHistory {self.pk}"
