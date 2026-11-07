"""Which doctor's work each so'm a patient paid was for.

Payments are not tied to procedures: a patient pays towards their balance.
To pay doctors a share of what was actually collected, every payment is
applied to the patient's oldest unpaid procedure first (FIFO). Money paid in
advance waits as credit and is applied when the next procedure is performed.
An allocation is dated when both the money and the work exist, i.e. the later
of the payment and the procedure.

Voiding a payment or a procedure re-runs the allocation, so the months it
touches change; payroll keeps that honest through the running balance.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.billing.balance import PROCEDURE_TOTAL
from apps.billing.models import Payment
from apps.dental.models import Procedure

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Allocation:
    doctor_id: object
    procedure_id: object
    at: datetime
    amount: Decimal


@dataclass(frozen=True)
class Unpaid:
    """What is still owed on one procedure when the run stops."""

    doctor_id: object
    procedure_id: object
    amount: Decimal


def run(clinic_ids, until: datetime) -> tuple[list[Allocation], list[Unpaid]]:
    """Allocations of live payments to live procedures, both strictly before `until`,
    and what is left unpaid on each procedure at that point."""
    events = defaultdict(list)
    procedures = (
        Procedure.objects.filter(clinic_id__in=clinic_ids, voided_at__isnull=True, performed_at__lt=until)
        .annotate(line_total=PROCEDURE_TOTAL)
        .values_list("patient_id", "performed_at", "doctor_id", "pk", "line_total")
    )
    for patient_id, at, doctor_id, procedure_id, total in procedures:
        # Procedures sort before payments at the same instant: a payment taken
        # at the chair is for the work just done. The id breaks ties so that
        # two runs over the same rows always agree.
        events[patient_id].append((at, 0, str(procedure_id), doctor_id, procedure_id, Decimal(total).quantize(CENT)))
    payments = Payment.objects.filter(clinic_id__in=clinic_ids, voided_at__isnull=True, paid_at__lt=until).values_list(
        "patient_id", "paid_at", "pk", "amount"
    )
    for patient_id, at, payment_id, amount in payments:
        events[patient_id].append((at, 1, str(payment_id), None, None, amount))

    allocations: list[Allocation] = []
    unpaid_left: list[Unpaid] = []
    for patient_events in events.values():
        patient_events.sort(key=lambda event: event[:3])
        unpaid: list[list] = []  # [doctor_id, procedure_id, remaining]
        credit = Decimal("0")
        for at, kind, _, doctor_id, procedure_id, amount in patient_events:
            if kind == 0:
                unpaid.append([doctor_id, procedure_id, amount])
            else:
                credit += amount
            while credit > 0 and unpaid:
                line = unpaid[0]
                applied = min(credit, line[2])
                if applied > 0:
                    allocations.append(Allocation(line[0], line[1], at, applied))
                credit -= applied
                line[2] -= applied
                if line[2] <= 0:
                    unpaid.pop(0)
        unpaid_left.extend(
            Unpaid(doctor_id, procedure_id, left) for doctor_id, procedure_id, left in unpaid if left > 0
        )
    return allocations, unpaid_left


def allocate(clinic_ids, until: datetime) -> list[Allocation]:
    return run(clinic_ids, until)[0]
