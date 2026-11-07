from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import BaseModel


class Category(models.TextChoices):
    DOCTOR_SHARE = "doctor_share", "Doctor share"
    STAFF_SALARY = "staff_salary", "Staff salary"
    RENT = "rent", "Rent"
    UTILITIES = "utilities", "Utilities"
    COMMUNICATION = "communication", "Phone and internet"
    MATERIALS = "materials", "Materials"
    LAB = "lab", "Dental lab"
    EQUIPMENT = "equipment", "Equipment"
    MARKETING = "marketing", "Marketing"
    TAXES_FEES = "taxes_fees", "Taxes and fees"
    OTHER = "other", "Other"


# What people are paid. Only owners see these rows: an admin entering rent has
# no business reading a colleague's salary.
PAYROLL_CATEGORIES = frozenset({Category.DOCTOR_SHARE, Category.STAFF_SALARY})

# The three questions an owner asks of costs: people, what is owed every month
# whatever the patient flow, and what moves with the work.
CATEGORY_KIND = {
    Category.DOCTOR_SHARE: "payroll",
    Category.STAFF_SALARY: "payroll",
    Category.RENT: "fixed",
    Category.UTILITIES: "fixed",
    Category.COMMUNICATION: "fixed",
    Category.TAXES_FEES: "fixed",
    Category.MATERIALS: "variable",
    Category.LAB: "variable",
    Category.EQUIPMENT: "variable",
    Category.MARKETING: "variable",
    Category.OTHER: "variable",
}


class Method(models.TextChoices):
    CASH = "cash", "Cash"
    CARD = "card", "Card"
    TRANSFER = "transfer", "Bank transfer"


MONEY = {"max_digits": 12, "decimal_places": 2}


class RecurringExpense(BaseModel):
    """A payment owed every month (rent, a utility, a salary).

    Only a reminder: each month is still paid by hand at its real amount, which
    creates an `Expense`. Switched off, never deleted, so past months keep their
    history.
    """

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="recurring_expenses")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=32, choices=Category.choices)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.CASH)
    payee = models.CharField(max_length=120, blank=True)
    day_of_month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(28)])
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["day_of_month", "name"]

    def __str__(self):
        return f"RecurringExpense {self.pk}"


class Expense(BaseModel):
    """Money the clinic paid out, entered by staff.

    Never edited or deleted: a mistake is voided with a reason and entered
    again, so the cost of any past month stays reproducible.
    """

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="expenses")
    category = models.CharField(max_length=32, choices=Category.choices)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=16, choices=Method.choices)
    spent_on = models.DateField()
    payee = models.CharField(max_length=120, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    # A doctor's share is paid for one doctor and one month of their work.
    doctor = models.ForeignKey(
        "tenancy.Membership", on_delete=models.PROTECT, null=True, blank=True, related_name="share_payouts"
    )
    # First day of the month this payment settles (a doctor's share or a recurring slot).
    period = models.DateField(null=True, blank=True)
    recurring = models.ForeignKey(
        RecurringExpense, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    created_by = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey("tenancy.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-spent_on", "-created_at"]
        indexes = [models.Index(fields=["clinic", "spent_on"])]
        constraints = [
            # One live payment per recurring slot; voiding it frees the slot.
            models.UniqueConstraint(
                fields=["recurring", "period"],
                condition=models.Q(recurring__isnull=False, voided_at__isnull=True),
                name="uniq_live_recurring_payment",
            )
        ]

    def __str__(self):
        return f"Expense {self.pk}"


class RecurringSkip(BaseModel):
    """A month in which a recurring payment is deliberately not owed."""

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="+")
    recurring = models.ForeignKey(RecurringExpense, on_delete=models.PROTECT, related_name="skips")
    period = models.DateField()
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="+")

    class Meta(BaseModel.Meta):
        constraints = [models.UniqueConstraint(fields=["recurring", "period"], name="uniq_recurring_skip")]

    def __str__(self):
        return f"RecurringSkip {self.pk}"


class Compensation(BaseModel):
    """A doctor's pay terms from one month on.

    A change is a new row, never an edit, so months already paid keep the terms
    they were computed under. The newest row at or before a month applies.
    """

    class Base(models.TextChoices):
        # Default: a doctor is not paid a share of money the patient still owes.
        COLLECTED = "collected", "Money collected for the doctor's work"
        BILLED = "billed", "Price of the doctor's work"

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="compensations")
    doctor = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="compensations")
    percent = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    fixed = models.DecimalField(**MONEY, default=Decimal("0"), validators=[MinValueValidator(0)])
    base = models.CharField(max_length=16, choices=Base.choices, default=Base.COLLECTED)
    effective_from = models.DateField()
    created_by = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="+")

    class Meta(BaseModel.Meta):
        ordering = ["-effective_from", "-created_at"]

    def __str__(self):
        return f"Compensation {self.pk}"
