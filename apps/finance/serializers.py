from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.finance.models import PAYROLL_CATEGORIES, Category, Compensation, Expense, Method, RecurringExpense
from apps.finance.periods import local_day, month_of, parse_month
from apps.tenancy.fields import ClinicRelatedField
from apps.tenancy.models import Membership
from apps.tenancy.permissions import permissions_for

DOCTORS = {"role": Membership.Role.DOCTOR}


def may_record_pay(request) -> bool:
    return "payroll:manage" in permissions_for(request.membership)


def clinic_today(request):
    return local_day(timezone.now(), ZoneInfo(request.clinic.timezone))


@extend_schema_field({"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$", "example": "2026-11"})
class MonthField(serializers.Field):
    """`YYYY-MM` on the wire, the first day of the month in the database."""

    default_error_messages = {"invalid": "Expected YYYY-MM."}

    def to_representation(self, value):
        return value.strftime("%Y-%m")

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return parse_month(data, self.field_name)


class ExpenseSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    doctor = ClinicRelatedField(
        queryset=Membership.objects.all(), extra_filter=DOCTORS, required=False, allow_null=True
    )
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True, default=None)
    period = MonthField(required=False, allow_null=True)
    created_by_name = serializers.CharField(source="created_by.user.full_name", read_only=True)
    spent_on = serializers.DateField(required=False)

    class Meta:
        model = Expense
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "category",
            "amount",
            "method",
            "spent_on",
            "payee",
            "notes",
            "doctor",
            "doctor_name",
            "period",
            "recurring",
            "created_by",
            "created_by_name",
            "voided_at",
            "void_reason",
        ]
        read_only_fields = ["id", "clinic", "recurring", "created_by", "voided_at", "void_reason"]
        # The one-live-payment-per-slot constraint only concerns `pay`, which
        # handles it; DRF would otherwise make `recurring` and `period` required.
        validators = []

    def validate(self, attrs):
        request = self.context["request"]
        today = clinic_today(request)
        attrs.setdefault("spent_on", today)
        if attrs["spent_on"] > today:
            raise serializers.ValidationError({"spent_on": "An expense cannot be in the future."}, code="invalid")
        category = attrs["category"]
        if category == Category.DOCTOR_SHARE:
            if attrs.get("doctor") is None:
                raise serializers.ValidationError({"doctor": "Choose the doctor."}, code="required")
            attrs.setdefault("period", month_of(attrs["spent_on"]))
            if attrs["period"] is None:
                raise serializers.ValidationError({"period": "Choose the month."}, code="required")
        elif attrs.get("doctor") is not None:
            raise serializers.ValidationError({"doctor": "Only a doctor's share names a doctor."}, code="invalid")
        if category in PAYROLL_CATEGORIES and not may_record_pay(request):
            raise serializers.ValidationError({"category": "Only the owner records pay."}, code="forbidden")
        return attrs


class RecurringExpenseSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)

    class Meta:
        model = RecurringExpense
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "name",
            "category",
            "amount",
            "method",
            "payee",
            "day_of_month",
            "is_active",
        ]
        read_only_fields = ["id", "clinic"]

    def validate_category(self, value):
        # A share is computed from the doctor's work, so it never repeats at a fixed amount.
        if value == Category.DOCTOR_SHARE:
            raise serializers.ValidationError("A doctor's share is paid from payroll.", code="invalid")
        if value in PAYROLL_CATEGORIES and not may_record_pay(self.context["request"]):
            raise serializers.ValidationError("Only the owner records pay.", code="forbidden")
        return value


class RecurringPaySerializer(serializers.Serializer):
    month = MonthField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False)
    method = serializers.ChoiceField(choices=Method.choices, required=False)
    spent_on = serializers.DateField(required=False)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RecurringSkipSerializer(serializers.Serializer):
    month = MonthField()
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class MonthSerializer(serializers.Serializer):
    month = MonthField()


class DueItemSerializer(serializers.Serializer):
    recurring = serializers.UUIDField()
    name = serializers.CharField()
    category = serializers.ChoiceField(choices=Category.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    method = serializers.ChoiceField(choices=Method.choices)
    payee = serializers.CharField()
    due_date = serializers.DateField()
    status = serializers.ChoiceField(choices=["due", "overdue", "paid", "skipped"])
    expense = serializers.UUIDField(allow_null=True)
    paid_amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    paid_on = serializers.DateField(allow_null=True)
    skip_reason = serializers.CharField(allow_null=True)


class DueTotalsSerializer(serializers.Serializer):
    expected = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    remaining = serializers.DecimalField(max_digits=14, decimal_places=2)


class DueMonthSerializer(serializers.Serializer):
    month = MonthField()
    totals = DueTotalsSerializer()
    items = DueItemSerializer(many=True)


class CompensationSerializer(serializers.ModelSerializer):
    doctor = ClinicRelatedField(queryset=Membership.objects.all(), extra_filter=DOCTORS)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    effective_from = MonthField()
    created_by_name = serializers.CharField(source="created_by.user.full_name", read_only=True)

    class Meta:
        model = Compensation
        fields = [
            "id",
            "clinic",
            "doctor",
            "doctor_name",
            "percent",
            "fixed",
            "base",
            "effective_from",
            "created_by",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "clinic", "created_by", "created_at"]


class PayrollRowSerializer(serializers.Serializer):
    doctor = serializers.UUIDField(source="doctor.pk")
    doctor_name = serializers.CharField(source="doctor.user.full_name")
    clinic_name = serializers.CharField(source="doctor.clinic.name")
    is_active = serializers.BooleanField(source="doctor.is_active")
    compensation = CompensationSerializer(allow_null=True)
    billed = serializers.DecimalField(max_digits=14, decimal_places=2)
    collected = serializers.DecimalField(max_digits=14, decimal_places=2)
    base_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    accrued = serializers.DecimalField(max_digits=14, decimal_places=2)
    opening = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)


class PayrollTotalsSerializer(serializers.Serializer):
    accrued = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)


class PayrollSerializer(serializers.Serializer):
    month = MonthField()
    rows = PayrollRowSerializer(many=True)
    totals = PayrollTotalsSerializer()


class PayoutSerializer(serializers.Serializer):
    doctor = ClinicRelatedField(queryset=Membership.objects.all(), extra_filter=DOCTORS)
    month = MonthField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=Method.choices)
    spent_on = serializers.DateField(required=False)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


def _money(**kwargs):
    return serializers.DecimalField(max_digits=14, decimal_places=2, **kwargs)


class ExpenseTotalsSerializer(serializers.Serializer):
    total = _money()
    count = serializers.IntegerField()
    payroll = _money()
    fixed = _money()
    variable = _money()


class CategoryAmountSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=Category.choices)
    amount = _money()


class SeriesAmountSerializer(serializers.Serializer):
    start = serializers.DateField()
    amount = _money()


class RangeFields(serializers.Serializer):
    # `from` is a Python keyword, so the field is declared under its wire name below.
    to = serializers.DateField()
    bucket = serializers.ChoiceField(choices=["day", "week", "month"])

    def get_fields(self):
        fields = super().get_fields()
        return {"from": serializers.DateField(), **fields}


class ExpenseSummarySerializer(RangeFields):
    totals = ExpenseTotalsSerializer()
    previous_totals = ExpenseTotalsSerializer()
    by_category = CategoryAmountSerializer(many=True)
    series = SeriesAmountSerializer(many=True)


class IncomeTotalsSerializer(serializers.Serializer):
    billed = _money()
    collected = _money()
    expenses = _money()
    profit = _money(allow_null=True)


class FinanceTotalsSerializer(IncomeTotalsSerializer):
    outstanding_debt = _money()
    debtors_count = serializers.IntegerField()


class FinanceSeriesSerializer(serializers.Serializer):
    start = serializers.DateField()
    billed = _money()
    collected = _money()
    expenses = _money()


class MethodAmountSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Method.choices)
    amount = _money()


class DoctorAmountSerializer(serializers.Serializer):
    doctor = serializers.UUIDField()
    doctor_name = serializers.CharField()
    clinic_name = serializers.CharField()
    billed = _money()
    collected = _money()


class ServiceAmountSerializer(serializers.Serializer):
    service = serializers.UUIDField()
    service_name = serializers.CharField()
    count = serializers.IntegerField()
    billed = _money()


class FinanceOverviewSerializer(RangeFields):
    totals = FinanceTotalsSerializer()
    previous_totals = IncomeTotalsSerializer()
    includes_payroll = serializers.BooleanField()
    series = FinanceSeriesSerializer(many=True)
    payment_methods = MethodAmountSerializer(many=True)
    doctors = DoctorAmountSerializer(many=True)
    services = ServiceAmountSerializer(many=True)


class StatisticsTotalsSerializer(serializers.Serializer):
    appointments = serializers.IntegerField()
    appointments_completed = serializers.IntegerField()
    no_shows = serializers.IntegerField()
    cancellations = serializers.IntegerField()
    new_patients = serializers.IntegerField()
    returning_patients = serializers.IntegerField()
    procedures = serializers.IntegerField()
    plans_accepted = serializers.IntegerField()


class AppointmentsPointSerializer(serializers.Serializer):
    start = serializers.DateField()
    total = serializers.IntegerField()
    completed = serializers.IntegerField()


class CountPointSerializer(serializers.Serializer):
    start = serializers.DateField()
    count = serializers.IntegerField()


class DoctorLoadSerializer(serializers.Serializer):
    doctor = serializers.UUIDField()
    doctor_name = serializers.CharField()
    clinic_name = serializers.CharField()
    appointments = serializers.IntegerField()
    appointments_completed = serializers.IntegerField()
    procedures = serializers.IntegerField()


class ServiceCountSerializer(serializers.Serializer):
    service = serializers.UUIDField()
    service_name = serializers.CharField()
    count = serializers.IntegerField()


class BusySlotSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=1, max_value=7, help_text="ISO weekday, 1 = Monday.")
    hour = serializers.IntegerField(min_value=0, max_value=23, help_text="Clinic-time hour.")
    appointments = serializers.IntegerField()


class ToothCountSerializer(serializers.Serializer):
    tooth = serializers.IntegerField(help_text="FDI number.")
    count = serializers.IntegerField()


class StatisticsOverviewSerializer(RangeFields):
    totals = StatisticsTotalsSerializer()
    previous_totals = StatisticsTotalsSerializer()
    appointments_series = AppointmentsPointSerializer(many=True)
    procedures_series = CountPointSerializer(many=True)
    doctors = DoctorLoadSerializer(many=True)
    services = ServiceCountSerializer(many=True)
    busy_slots = BusySlotSerializer(many=True)
    teeth = ToothCountSerializer(many=True)
