"""Sums for the finance screens. The browser shows totals; it never adds money up."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate

from apps.billing.balance import PROCEDURE_TOTAL, annotate_balance
from apps.billing.models import Payment
from apps.dental.models import Procedure
from apps.finance.allocation import allocate
from apps.finance.models import CATEGORY_KIND, PAYROLL_CATEGORIES, Expense
from apps.finance.periods import DateRange, start_of
from apps.patients.models import Patient
from apps.tenancy.models import Membership

ZERO = Decimal("0.00")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def visible_expenses(clinic_ids, *, include_payroll: bool):
    queryset = Expense.objects.filter(clinic_id__in=clinic_ids, voided_at__isnull=True)
    if not include_payroll:
        queryset = queryset.exclude(category__in=PAYROLL_CATEGORIES)
    return queryset


def expense_totals(queryset) -> dict:
    totals = {"total": ZERO, "count": 0, "payroll": ZERO, "fixed": ZERO, "variable": ZERO}
    for category, amount, count in queryset.values_list("category").annotate(t=Sum("amount"), c=Count("id")):
        totals["total"] += amount
        totals["count"] += count
        totals[CATEGORY_KIND[category]] += amount
    return totals


def expense_summary(clinic_ids, period: DateRange, *, include_payroll: bool) -> dict:
    base = visible_expenses(clinic_ids, include_payroll=include_payroll)
    current = base.filter(spent_on__range=(period.start, period.end))
    previous_range = period.previous()
    previous = base.filter(spent_on__range=(previous_range.start, previous_range.end))

    by_category = [
        {"category": category, "amount": amount}
        for category, amount in current.values_list("category").annotate(total=Sum("amount")).order_by("-total")
    ]
    series = defaultdict(Decimal)
    for day, amount in current.values_list("spent_on").annotate(t=Sum("amount")):
        series[period.bucket_start(day)] += amount
    return {
        "from": period.start,
        "to": period.end,
        "bucket": period.bucket,
        "totals": expense_totals(current),
        "previous_totals": expense_totals(previous),
        "by_category": by_category,
        "series": [{"start": start, "amount": series[start]} for start in period.buckets()],
    }


def window(period: DateRange, zone):
    return start_of(period.start, zone), start_of(period.end + timedelta(days=1), zone)


def _income_totals(clinic_ids, period: DateRange, zone, *, include_payroll: bool) -> dict:
    start, end = window(period, zone)
    billed = (
        Procedure.objects.filter(clinic_id__in=clinic_ids, voided_at__isnull=True, performed_at__gte=start)
        .filter(performed_at__lt=end)
        .aggregate(s=Sum(PROCEDURE_TOTAL))["s"]
    )
    collected = Payment.objects.filter(
        clinic_id__in=clinic_ids, voided_at__isnull=True, paid_at__gte=start, paid_at__lt=end
    ).aggregate(s=Sum("amount"))["s"]
    expenses = expense_totals(
        visible_expenses(clinic_ids, include_payroll=include_payroll).filter(spent_on__range=(period.start, period.end))
    )["total"]
    return {
        "billed": money(billed),
        "collected": money(collected),
        "expenses": money(expenses),
        # Without payroll the difference is not a profit, so none is claimed.
        "profit": money(collected) - money(expenses) if include_payroll else None,
    }


def finance_overview(clinic_ids, period: DateRange, zone, *, include_payroll: bool) -> dict:
    start, end = window(period, zone)
    procedures = Procedure.objects.filter(
        clinic_id__in=clinic_ids, voided_at__isnull=True, performed_at__gte=start, performed_at__lt=end
    )
    payments = Payment.objects.filter(clinic_id__in=clinic_ids, voided_at__isnull=True, paid_at__gte=start)
    payments = payments.filter(paid_at__lt=end)

    series = defaultdict(lambda: {"billed": ZERO, "collected": ZERO, "expenses": ZERO})
    for day, total in (
        procedures.annotate(day=TruncDate("performed_at", tzinfo=zone))
        .values_list("day")
        .annotate(t=Sum(PROCEDURE_TOTAL))
    ):
        series[period.bucket_start(day)]["billed"] += money(total)
    for day, total in (
        payments.annotate(day=TruncDate("paid_at", tzinfo=zone)).values_list("day").annotate(t=Sum("amount"))
    ):
        series[period.bucket_start(day)]["collected"] += money(total)
    expenses = visible_expenses(clinic_ids, include_payroll=include_payroll).filter(
        spent_on__range=(period.start, period.end)
    )
    for day, total in expenses.values_list("spent_on").annotate(t=Sum("amount")):
        series[period.bucket_start(day)]["expenses"] += money(total)

    doctors = defaultdict(lambda: {"billed": ZERO, "collected": ZERO})
    for doctor_id, total in procedures.values_list("doctor_id").annotate(t=Sum(PROCEDURE_TOTAL)):
        doctors[doctor_id]["billed"] += money(total)
    for allocation in allocate(clinic_ids, end):
        if allocation.at >= start:
            doctors[allocation.doctor_id]["collected"] += allocation.amount
    members = Membership.objects.filter(pk__in=list(doctors)).select_related("user", "clinic")

    debtors = annotate_balance(Patient.objects.filter(clinic_id__in=clinic_ids)).filter(debt__gt=0)
    debt = debtors.aggregate(total=Sum("debt"), count=Count("id"))

    return {
        "from": period.start,
        "to": period.end,
        "bucket": period.bucket,
        "totals": {
            **_income_totals(clinic_ids, period, zone, include_payroll=include_payroll),
            "outstanding_debt": money(debt["total"]),
            "debtors_count": debt["count"],
        },
        "previous_totals": _income_totals(clinic_ids, period.previous(), zone, include_payroll=include_payroll),
        "includes_payroll": include_payroll,
        "series": [{"start": day, **series[day]} for day in period.buckets()],
        "payment_methods": [
            {"method": method, "amount": money(total)}
            for method, total in payments.values_list("method").annotate(t=Sum("amount")).order_by("-t")
        ],
        "doctors": sorted(
            (
                {
                    "doctor": member.pk,
                    "doctor_name": member.user.full_name,
                    "clinic_name": member.clinic.name,
                    **doctors[member.pk],
                }
                for member in members
            ),
            key=lambda row: (-row["billed"], row["doctor_name"]),
        ),
        "services": [
            {"service": service_id, "service_name": name, "count": count, "billed": money(total)}
            for service_id, name, count, total in procedures.values_list("service_id", "service__name")
            .annotate(c=Count("id"), t=Sum(PROCEDURE_TOTAL))
            .order_by("-t")[:10]
        ],
    }
