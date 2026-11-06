from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import BaseModel
from apps.core.validators import validate_fdi_tooth

SURFACES = ("M", "O", "D", "B", "L", "I")  # mesial, occlusal, distal, buccal, lingual, incisal


class ToothCondition(models.TextChoices):
    HEALTHY = "healthy", "Healthy"
    CARIES = "caries", "Caries"
    FILLED = "filled", "Filled"
    ROOT_CANAL = "root_canal", "Root canal treated"
    CROWN = "crown", "Crown"
    BRIDGE = "bridge", "Bridge"
    IMPLANT = "implant", "Implant"
    MISSING = "missing", "Missing"
    EXTRACTION_NEEDED = "extraction_needed", "Extraction needed"
    FRACTURE = "fracture", "Fracture"


class ToothRecord(BaseModel):
    """Current state of one tooth on a patient's dental chart (odontogram)."""

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="tooth_records")
    tooth = models.PositiveSmallIntegerField(validators=[validate_fdi_tooth])
    condition = models.CharField(max_length=24, choices=ToothCondition.choices)
    surfaces = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey("tenancy.Membership", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta(BaseModel.Meta):
        ordering = ["tooth"]
        constraints = [models.UniqueConstraint(fields=["patient", "tooth"], name="uniq_tooth_per_patient")]

    def __str__(self):
        return f"ToothRecord {self.pk}"


class ToothEvent(BaseModel):
    """Append-only history of chart changes, so earlier states can be shown."""

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="tooth_events")
    tooth = models.PositiveSmallIntegerField(validators=[validate_fdi_tooth])
    condition = models.CharField(max_length=24, choices=ToothCondition.choices)
    surfaces = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey("tenancy.Membership", on_delete=models.SET_NULL, null=True, related_name="+")

    def __str__(self):
        return f"ToothEvent {self.pk}"


class PricedLine(models.Model):
    """Price fields shared by plan items and procedures. The price is copied from
    the service at the time, so later price list changes do not rewrite history."""

    quantity = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    class Meta:
        abstract = True

    @property
    def total(self) -> Decimal:
        gross = self.unit_price * self.quantity
        return (gross * (Decimal(100) - self.discount_percent) / Decimal(100)).quantize(Decimal("0.01"))


class TreatmentPlan(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PRESENTED = "presented", "Presented to patient"
        ACCEPTED = "accepted", "Accepted"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    EDITABLE = (Status.DRAFT, Status.PRESENTED)

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="treatment_plans")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="treatment_plans")
    doctor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="treatment_plans")
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"TreatmentPlan {self.pk}"


class PlanItem(BaseModel, PricedLine):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="+")
    tooth = models.PositiveSmallIntegerField(null=True, blank=True, validators=[validate_fdi_tooth])
    surfaces = models.JSONField(default=list, blank=True)
    phase = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED)
    notes = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["phase", "created_at"]

    def __str__(self):
        return f"PlanItem {self.pk}"


class Procedure(BaseModel, PricedLine):
    """A procedure actually performed. It is the charge the patient owes.

    Never deleted: a mistaken entry is voided with a reason, so the patient's
    balance history stays explainable.
    """

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="procedures")
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="procedures")
    doctor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="procedures")
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="+")
    plan_item = models.OneToOneField(
        PlanItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="procedure"
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment", on_delete=models.SET_NULL, null=True, blank=True, related_name="procedures"
    )
    tooth = models.PositiveSmallIntegerField(null=True, blank=True, validators=[validate_fdi_tooth])
    surfaces = models.JSONField(default=list, blank=True)
    performed_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey("tenancy.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-performed_at"]
        indexes = [models.Index(fields=["clinic", "performed_at"])]

    def __str__(self):
        return f"Procedure {self.pk}"
