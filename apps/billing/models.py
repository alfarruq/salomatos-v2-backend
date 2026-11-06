from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import BaseModel


class Payment(BaseModel):
    """Money received from a patient, entered by staff (no online gateways).

    Never deleted or edited after the fact: a mistake is voided with a reason
    and entered again, so the cash total of any past day stays reproducible.
    """

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        TRANSFER = "transfer", "Bank transfer"

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="payments")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=16, choices=Method.choices)
    paid_at = models.DateTimeField()
    received_by = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="+")
    notes = models.CharField(max_length=255, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey("tenancy.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-paid_at"]
        indexes = [models.Index(fields=["clinic", "paid_at"])]

    def __str__(self):
        return f"Payment {self.pk}"
