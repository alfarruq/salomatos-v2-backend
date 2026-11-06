from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import BaseModel


class ServiceCategory(BaseModel):
    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.CASCADE, related_name="service_categories")
    name = models.CharField(max_length=255)

    class Meta(BaseModel.Meta):
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["clinic", "name"], name="uniq_service_category")]

    def __str__(self):
        return self.name


class Service(BaseModel):
    """A billable procedure in the clinic's price list (filling, extraction, implant)."""

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.CASCADE, related_name="services")
    category = models.ForeignKey(
        ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="services"
    )
    specialty = models.ForeignKey(
        "tenancy.Specialty", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    code = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["name"]

    def __str__(self):
        return self.name
