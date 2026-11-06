from django.db import models

from apps.core.models import BaseModel


class Prescription(BaseModel):
    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="prescriptions")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="prescriptions")
    doctor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="prescriptions")
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Prescription {self.pk}"


class PrescriptionItem(BaseModel):
    class MealRelation(models.TextChoices):
        BEFORE = "before", "Before meal"
        AFTER = "after", "After meal"
        WITH = "with", "With meal"
        ANY = "any", "Any time"

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    medicine = models.CharField(max_length=255)
    dose = models.CharField(max_length=64)
    form = models.CharField(max_length=64, blank=True)
    times_per_day = models.PositiveSmallIntegerField()
    duration_days = models.PositiveSmallIntegerField()
    meal_relation = models.CharField(max_length=8, choices=MealRelation.choices, default=MealRelation.ANY)
    instructions = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["created_at"]
