from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class BotAccount(BaseModel):
    """A Telegram bot login, issued by the system for one patient or one staff user.

    Patients have no web login; this is their only way in. The password is kept
    twice: hashed, to check a login, and encrypted, because the clinic asked to
    be able to read it back to a patient who forgot it. Every read-back is audited.
    """

    class Kind(models.TextChoices):
        PATIENT = "patient", "Patient"
        STAFF = "staff", "Staff"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    patient = models.OneToOneField(
        "patients.Patient", on_delete=models.CASCADE, null=True, blank=True, related_name="bot_account"
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="bot_account"
    )
    # The patient's branch; staff accounts span the user's memberships instead.
    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    login = models.CharField(max_length=16, unique=True)
    password_hash = models.CharField(max_length=128)
    password_encrypted = models.TextField()
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="patient", patient__isnull=False, user__isnull=True)
                    | models.Q(kind="staff", patient__isnull=True, user__isnull=False)
                ),
                name="bot_account_one_subject",
            )
        ]

    def __str__(self):
        return f"BotAccount {self.pk}"


class AppointmentReminder(BaseModel):
    """A reminder already sent, so a restart or a second bot process never repeats one.

    `for_start_at` is part of the key: a booking that was moved is a new visit
    and gets its own reminders. The row is written before the send, so a failed
    send is lost rather than retried every few minutes at a blocked chat.
    """

    class Kind(models.TextChoices):
        DAY_BEFORE = "day_before", "Day before"
        TWO_HOURS = "two_hours", "Two hours before"

    appointment = models.ForeignKey("scheduling.Appointment", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    for_start_at = models.DateTimeField()

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["appointment", "kind", "for_start_at"], name="uniq_appointment_reminder")
        ]

    def __str__(self):
        return f"AppointmentReminder {self.pk}"
