"""A doctor's month: what they earned, what was paid, what is still owed."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Q

from apps.billing.balance import PROCEDURE_TOTAL
from apps.dental.models import Procedure
from apps.finance.allocation import CENT, run
from apps.finance.models import Category, Compensation, Expense
from apps.finance.periods import add_months, local_day, month_of, start_of
from apps.tenancy.models import Clinic, Membership

ZERO = Decimal("0.00")


@dataclass
class PayrollRow:
    doctor: Membership
    compensation: Compensation | None
    billed: Decimal = ZERO
    collected: Decimal = ZERO
    base_amount: Decimal = ZERO
    accrued: Decimal = ZERO
    opening: Decimal = ZERO
    paid: Decimal = ZERO
    balance: Decimal = ZERO
    # Work done by the month's end that patients have not paid for yet, and the
    # doctor's share of it once they do. Not owed yet, so not in the balance.
    pending: Decimal = ZERO
    pending_share: Decimal = ZERO


@dataclass
class _History:
    billed: dict = field(default_factory=lambda: defaultdict(Decimal))
    collected: dict = field(default_factory=lambda: defaultdict(Decimal))
    paid: dict = field(default_factory=lambda: defaultdict(Decimal))


def terms_for(history: list[Compensation], month: date) -> Compensation | None:
    """`history` newest first, as `Compensation.Meta.ordering` returns it."""
    return next((terms for terms in history if terms.effective_from <= month), None)


def accrual(terms: Compensation | None, billed: Decimal, collected: Decimal) -> tuple[Decimal, Decimal]:
    """(base amount, accrued) for one month under `terms`."""
    if terms is None:
        return ZERO, ZERO
    base = collected if terms.base == Compensation.Base.COLLECTED else billed
    return base, (terms.fixed + base * terms.percent / Decimal(100)).quantize(CENT)


def pending_share(terms: Compensation | None, pending: Decimal) -> Decimal:
    if terms is None or terms.base != Compensation.Base.COLLECTED:
        # On billed terms the work already counted when it was done.
        return ZERO
    return (pending * terms.percent / Decimal(100)).quantize(CENT)


def compute(clinic: Clinic, month: date, *, doctor: Membership | None = None) -> list[PayrollRow]:
    zone = ZoneInfo(clinic.timezone)
    until = start_of(add_months(month, 1), zone)

    compensations = defaultdict(list)
    for terms in Compensation.objects.filter(clinic=clinic, effective_from__lt=add_months(month, 1)):
        compensations[terms.doctor_id].append(terms)

    doctors = (
        Membership.objects.filter(clinic=clinic)
        .filter(Q(role=Membership.Role.DOCTOR, is_active=True) | Q(pk__in=list(compensations)))
        .select_related("user", "clinic")
        .order_by("user__full_name")
    )
    if doctor is not None:
        doctors = doctors.filter(pk=doctor.pk)

    history: dict = defaultdict(_History)
    procedures = (
        Procedure.objects.filter(clinic=clinic, voided_at__isnull=True, performed_at__lt=until)
        .annotate(line_total=PROCEDURE_TOTAL)
        .values_list("doctor_id", "performed_at", "line_total")
    )
    for doctor_id, at, total in procedures:
        history[doctor_id].billed[month_of(local_day(at, zone))] += Decimal(total).quantize(CENT)
    allocations, unpaid = run([clinic.pk], until)
    for allocation in allocations:
        history[allocation.doctor_id].collected[month_of(local_day(allocation.at, zone))] += allocation.amount
    pending = defaultdict(Decimal)
    for line in unpaid:
        pending[line.doctor_id] += line.amount
    payouts = Expense.objects.filter(
        clinic=clinic, category=Category.DOCTOR_SHARE, voided_at__isnull=True, period__lte=month
    ).values_list("doctor_id", "period", "amount")
    for doctor_id, period, amount in payouts:
        history[doctor_id].paid[period] += amount

    rows = []
    for doctor in doctors:
        terms_history = compensations.get(doctor.pk, [])
        past = history[doctor.pk]
        row = PayrollRow(doctor=doctor, compensation=terms_for(terms_history, month))
        # The running balance starts at the first month anything happened.
        months = [*past.billed, *past.collected, *past.paid, *(t.effective_from for t in terms_history)]
        current = min(months, default=month)
        while current < month:
            _, accrued = accrual(terms_for(terms_history, current), past.billed[current], past.collected[current])
            row.opening += accrued - past.paid[current]
            current = add_months(current, 1)
        row.billed = past.billed[month]
        row.collected = past.collected[month]
        row.base_amount, row.accrued = accrual(row.compensation, row.billed, row.collected)
        row.paid = past.paid[month]
        row.balance = row.opening + row.accrued - row.paid
        row.pending = pending[doctor.pk]
        row.pending_share = pending_share(row.compensation, row.pending)
        rows.append(row)
    return rows
