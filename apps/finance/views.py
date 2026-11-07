from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.dental.serializers import VoidSerializer
from apps.finance import payroll, reports, statistics
from apps.finance.models import PAYROLL_CATEGORIES, Category, Compensation, Expense, RecurringExpense, RecurringSkip
from apps.finance.periods import add_months, clinic_zone, local_day, parse_month, parse_range
from apps.finance.serializers import (
    CompensationSerializer,
    DueMonthSerializer,
    ExpenseSerializer,
    ExpenseSummarySerializer,
    FinanceOverviewSerializer,
    MonthSerializer,
    PayoutSerializer,
    PayrollSerializer,
    RecurringExpenseSerializer,
    RecurringPaySerializer,
    RecurringSkipSerializer,
    StatisticsOverviewSerializer,
    clinic_today,
)
from apps.tenancy.models import Clinic, Membership
from apps.tenancy.viewsets import ClinicScopedMixin

MONTH_PARAM = OpenApiParameter("month", OpenApiTypes.STR, required=True, description="YYYY-MM")
RANGE_PARAMS = [
    OpenApiParameter("from", OpenApiTypes.DATE, required=True),
    OpenApiParameter("to", OpenApiTypes.DATE, required=True),
]


def hide_payroll(view, queryset):
    """Rows of pay categories exist only for those who may see payroll."""
    if not view.has_perm("payroll:view"):
        queryset = queryset.exclude(category__in=PAYROLL_CATEGORIES)
    return queryset


class ExpenseFilter(filters.FilterSet):
    spent_from = filters.DateFilter(field_name="spent_on", lookup_expr="gte")
    spent_to = filters.DateFilter(field_name="spent_on", lookup_expr="lte")
    voided = filters.BooleanFilter(field_name="voided_at", lookup_expr="isnull", exclude=True)
    doctor = filters.UUIDFilter()
    recurring = filters.UUIDFilter()

    class Meta:
        model = Expense
        fields = ["category", "method"]


class ExpenseViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Expenses are entered and voided, never edited or deleted."""

    queryset = Expense.objects.select_related("clinic", "doctor__user", "created_by__user")
    serializer_class = ExpenseSerializer
    filterset_class = ExpenseFilter
    organization_actions = frozenset({"list", "retrieve", "summary"})
    required_permissions = {
        "list": "expense:view",
        "retrieve": "expense:view",
        "summary": "expense:view",
        "create": "expense:manage",
        "void": "expense:void",
    }

    def scope_queryset(self, queryset):
        return hide_payroll(self, queryset)

    def perform_create(self, serializer):
        serializer.validated_data["created_by"] = self.request.membership
        super().perform_create(serializer)

    @extend_schema(request=VoidSerializer, responses={200: ExpenseSerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def void(self, request, pk=None):
        expense = self.get_object()
        params = VoidSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        if expense.voided_at is not None:
            raise ValidationError("Already voided.", code="already_voided")
        expense.voided_at = timezone.now()
        expense.voided_by = request.membership
        expense.void_reason = params.validated_data["reason"]
        expense.save()
        record(request, AuditLog.Action.UPDATE, expense)
        return Response(self.get_serializer(expense).data)

    @extend_schema(parameters=RANGE_PARAMS, responses={200: ExpenseSummarySerializer})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        period = parse_range(request.query_params)
        data = reports.expense_summary(request.clinic_ids, period, include_payroll=self.has_perm("payroll:view"))
        return Response(ExpenseSummarySerializer(data).data)


class RecurringExpenseViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Monthly templates. Switched off with `is_active`, never deleted."""

    queryset = RecurringExpense.objects.select_related("clinic")
    serializer_class = RecurringExpenseSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    organization_actions = frozenset({"list", "retrieve", "due"})
    required_permissions = {
        "list": "expense:view",
        "retrieve": "expense:view",
        "due": "expense:view",
        "create": "expense:manage",
        "partial_update": "expense:manage",
        "pay": "expense:manage",
        "skip": "expense:manage",
        "unskip": "expense:manage",
    }

    def scope_queryset(self, queryset):
        return hide_payroll(self, queryset)

    @extend_schema(parameters=[MONTH_PARAM], responses={200: DueMonthSerializer})
    @action(detail=False, methods=["get"])
    def due(self, request):
        month = parse_month(request.query_params.get("month"))
        zone = clinic_zone(request)
        today = local_day(timezone.now(), zone)
        next_month = add_months(month, 1)
        templates = self.get_queryset()
        payments = {
            expense.recurring_id: expense
            for expense in Expense.objects.filter(
                recurring__in=templates, period=month, voided_at__isnull=True
            ).order_by("created_at")
        }
        skips = {
            skip.recurring_id: skip for skip in RecurringSkip.objects.filter(recurring__in=templates, period=month)
        }
        items = []
        totals = {"expected": Decimal("0"), "paid": Decimal("0"), "remaining": Decimal("0")}
        for template in templates:
            paid = payments.get(template.pk)
            skip = skips.get(template.pk)
            created = local_day(template.created_at, zone)
            # A template counts from the month it was created in, and an
            # inactive one only where it already has history.
            if created >= next_month or (not template.is_active and paid is None and skip is None):
                continue
            due_date = date(month.year, month.month, template.day_of_month)
            if paid is not None:
                status = "paid"
            elif skip is not None:
                status = "skipped"
            else:
                status = "overdue" if due_date < today else "due"
            if status != "skipped":
                totals["expected"] += template.amount
            if paid is not None:
                totals["paid"] += paid.amount
            if status in {"due", "overdue"}:
                totals["remaining"] += template.amount
            items.append(
                {
                    "recurring": template.pk,
                    "name": template.name,
                    "category": template.category,
                    "amount": template.amount,
                    "method": template.method,
                    "payee": template.payee,
                    "due_date": due_date,
                    "status": status,
                    "expense": paid.pk if paid else None,
                    "paid_amount": paid.amount if paid else None,
                    "paid_on": paid.spent_on if paid else None,
                    "skip_reason": skip.reason if skip else None,
                }
            )
        items.sort(key=lambda item: (item["due_date"], item["name"]))
        return Response(DueMonthSerializer({"month": month, "totals": totals, "items": items}).data)

    @extend_schema(request=RecurringPaySerializer, responses={201: ExpenseSerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def pay(self, request, pk=None):
        template = self.get_object()
        params = RecurringPaySerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        month = data["month"]
        if RecurringSkip.objects.filter(recurring=template, period=month).exists():
            raise ValidationError({"month": "This month is skipped."}, code="skipped")
        spent_on = data.get("spent_on") or clinic_today(request)
        if spent_on > clinic_today(request):
            raise ValidationError({"spent_on": "An expense cannot be in the future."}, code="invalid")
        try:
            with transaction.atomic():
                expense = Expense.objects.create(
                    clinic=request.clinic,
                    category=template.category,
                    amount=data.get("amount") or template.amount,
                    method=data.get("method") or template.method,
                    spent_on=spent_on,
                    payee=template.payee,
                    notes=data["notes"],
                    period=month,
                    recurring=template,
                    created_by=request.membership,
                )
        except IntegrityError:
            raise ValidationError({"month": "Already paid for this month."}, code="already_paid") from None
        record(request, AuditLog.Action.CREATE, expense)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data, status=201)

    @extend_schema(request=RecurringSkipSerializer, responses={204: None})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def skip(self, request, pk=None):
        template = self.get_object()
        params = RecurringSkipSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        month = params.validated_data["month"]
        if Expense.objects.filter(recurring=template, period=month, voided_at__isnull=True).exists():
            raise ValidationError({"month": "Already paid for this month."}, code="already_paid")
        skip, _ = RecurringSkip.objects.get_or_create(
            recurring=template,
            period=month,
            defaults={
                "clinic": request.clinic,
                "reason": params.validated_data["reason"],
                "created_by": request.membership,
            },
        )
        record(request, AuditLog.Action.CREATE, skip)
        return Response(status=204)

    @extend_schema(request=MonthSerializer, responses={204: None})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def unskip(self, request, pk=None):
        template = self.get_object()
        params = MonthSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        for skip in RecurringSkip.objects.filter(recurring=template, period=params.validated_data["month"]):
            record(request, AuditLog.Action.DELETE, skip)
            skip.delete()
        return Response(status=204)


class CompensationFilter(filters.FilterSet):
    doctor = filters.UUIDFilter()

    class Meta:
        model = Compensation
        fields = []


class CompensationViewSet(ClinicScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """A doctor's pay terms over time. A change is a new row, never an edit."""

    queryset = Compensation.objects.select_related("doctor__user", "created_by__user")
    serializer_class = CompensationSerializer
    filterset_class = CompensationFilter
    required_permissions = {"list": "payroll:view", "retrieve": "payroll:view", "create": "payroll:manage"}
    organization_actions = frozenset({"list", "retrieve"})

    def perform_create(self, serializer):
        serializer.validated_data["created_by"] = self.request.membership
        super().perform_create(serializer)


class PayrollViewSet(ClinicScopedMixin, viewsets.GenericViewSet):
    """Each doctor's month: accrued from their terms, paid out, and the running balance."""

    queryset = Membership.objects.all()
    serializer_class = PayrollSerializer
    organization_actions = frozenset({"list"})
    required_permissions = {"list": "payroll:view", "pay": "payroll:manage"}

    @extend_schema(parameters=[MONTH_PARAM], responses={200: PayrollSerializer})
    def list(self, request):
        month = parse_month(request.query_params.get("month"))
        rows = []
        for clinic in Clinic.objects.filter(pk__in=request.clinic_ids).order_by("name"):
            rows.extend(payroll.compute(clinic, month))
        totals = {key: sum((getattr(row, key) for row in rows), Decimal("0")) for key in ("accrued", "paid", "balance")}
        return Response(PayrollSerializer({"month": month, "rows": rows, "totals": totals}).data)

    @extend_schema(request=PayoutSerializer, responses={201: ExpenseSerializer})
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def pay(self, request):
        """Pays a doctor's share for a month. Recorded as a `doctor_share` expense."""
        params = PayoutSerializer(data=request.data, context=self.get_serializer_context())
        params.is_valid(raise_exception=True)
        data = params.validated_data
        spent_on = data.get("spent_on") or clinic_today(request)
        if spent_on > clinic_today(request):
            raise ValidationError({"spent_on": "An expense cannot be in the future."}, code="invalid")
        expense = Expense.objects.create(
            clinic=request.clinic,
            category=Category.DOCTOR_SHARE,
            amount=data["amount"],
            method=data["method"],
            spent_on=spent_on,
            notes=data["notes"],
            doctor=data["doctor"],
            period=data["month"],
            created_by=request.membership,
        )
        record(request, AuditLog.Action.CREATE, expense)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data, status=201)


class ReportViewSet(ClinicScopedMixin, viewsets.GenericViewSet):
    """Server-side sums for the report screens."""

    queryset = Clinic.objects.none()
    serializer_class = FinanceOverviewSerializer
    organization_actions = frozenset({"finance", "statistics"})
    required_permissions = {"finance": "report:view", "statistics": "report:view"}

    def get_queryset(self):
        return self.queryset

    @extend_schema(parameters=RANGE_PARAMS, responses={200: FinanceOverviewSerializer})
    @action(detail=False, methods=["get"])
    def finance(self, request):
        period = parse_range(request.query_params)
        data = reports.finance_overview(
            request.clinic_ids, period, clinic_zone(request), include_payroll=self.has_perm("payroll:view")
        )
        return Response(FinanceOverviewSerializer(data).data)

    @extend_schema(parameters=RANGE_PARAMS, responses={200: StatisticsOverviewSerializer})
    @action(detail=False, methods=["get"])
    def statistics(self, request):
        period = parse_range(request.query_params)
        data = statistics.statistics_overview(request.clinic_ids, period, clinic_zone(request))
        return Response(StatisticsOverviewSerializer(data).data)
