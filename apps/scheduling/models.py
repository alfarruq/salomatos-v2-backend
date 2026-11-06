from django.db import models

from apps.core.models import BaseModel


class Chair(BaseModel):
    """A dental chair or room. Two appointments cannot share one at the same time."""

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.CASCADE, related_name="chairs")
    name = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["clinic", "name"], name="uniq_chair")]

    def __str__(self):
        return self.name


class Appointment(BaseModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CONFIRMED = "confirmed", "Confirmed"
        ARRIVED = "arrived", "Arrived"
        IN_CHAIR = "in_chair", "In chair"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No show"
        CANCELLED = "cancelled", "Cancelled"

    # Statuses that still hold the time slot.
    BLOCKING = (Status.SCHEDULED, Status.CONFIRMED, Status.ARRIVED, Status.IN_CHAIR, Status.COMPLETED)

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="appointments")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="appointments")
    chair = models.ForeignKey(Chair, on_delete=models.SET_NULL, null=True, blank=True, related_name="appointments")
    service = models.ForeignKey("catalog.Service", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["clinic", "start_at"]),
            models.Index(fields=["doctor", "start_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_at__gt=models.F("start_at")), name="appointment_end_after_start"
            ),
        ]

    def __str__(self):
        return f"Appointment {self.pk}"
