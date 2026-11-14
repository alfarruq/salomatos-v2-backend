from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.core.validators import validate_phone


class Organization(BaseModel):
    """The customer that bought the install. One organization runs one or more clinics (branches).

    Owners see every branch: they hold an OWNER membership in each clinic of
    the organization (kept in sync by `apps.tenancy.services`). Branch admins
    and doctors are members of one clinic only and see nothing of the others.
    """

    name = models.CharField(max_length=255)
    owners = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="owned_organizations", blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Clinic(BaseModel):
    """The tenant. Every clinical or business row carries a FK to it."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="clinics")
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=16, validators=[validate_phone], blank=True)
    address = models.CharField(max_length=255, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Tashkent")
    working_hours = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["name"]

    def __str__(self):
        return self.name


class Specialty(BaseModel):
    """A doctor's specialty within one clinic (therapist, orthodontist, surgeon)."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="specialties")
    name = models.CharField(max_length=255)
    # The dentist specialty: every clinic has exactly one, created with the clinic and
    # never renamed or deleted, so the treatment form can rely on it for the tooth chart.
    is_dental = models.BooleanField(default=False, editable=False)

    class Meta(BaseModel.Meta):
        ordering = ["-is_dental", "name"]
        constraints = [
            models.UniqueConstraint(fields=["clinic", "name"], name="uniq_specialty_per_clinic"),
            models.UniqueConstraint(
                fields=["clinic"], condition=models.Q(is_dental=True), name="uniq_dental_specialty_per_clinic"
            ),
        ]

    def __str__(self):
        return self.name


class Membership(BaseModel):
    """A user's role in one clinic. This is the only source of permissions."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Administrator"
        DOCTOR = "doctor", "Doctor"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    # Doctor profile. Lives here, not on User, because it is per clinic.
    specialty = models.ForeignKey(Specialty, on_delete=models.SET_NULL, null=True, blank=True, related_name="doctors")
    experience_years = models.PositiveSmallIntegerField(null=True, blank=True)
    biography = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        constraints = [models.UniqueConstraint(fields=["user", "clinic"], name="uniq_membership")]

    def __str__(self):
        return f"{self.user} @ {self.clinic} ({self.role})"
