"""Moves patients from one branch to another of the same organization.

The owner's decision (2026-11-10): the clinical record moves, money does not.
Procedures and payments stay in the branch that performed and collected them,
so its finance reports, debtors and doctors' pay never change after the fact.
A patient therefore moves only with a zero balance and no unfinished
procedure; otherwise their old debt would be stranded where nobody sees it.

Doctors, chairs and the price list are per branch, so references are remapped:
the chosen target doctor takes over the patient and everything still ahead
(future visits, open plans); finished records keep their original author,
because rewriting who wrote a prescription would falsify the record.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.balance import annotate_balance
from apps.bot.models import BotAccount
from apps.catalog.models import Service
from apps.clinical.models import Prescription
from apps.dental.models import Procedure, ToothEvent, ToothRecord, TreatmentPlan
from apps.imaging.models import Attachment
from apps.patients.models import MedicalHistory, Patient
from apps.scheduling.models import Appointment
from apps.tenancy.models import Clinic, Membership

MAX_PATIENTS = 500
OPEN_PLAN = (TreatmentPlan.Status.DRAFT, TreatmentPlan.Status.PRESENTED, TreatmentPlan.Status.ACCEPTED)
UPCOMING = (Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED)


def blocked_patients(patients) -> list:
    """Ids of patients that cannot move: money left either way, or work still in progress."""
    with_balance = annotate_balance(patients).exclude(debt=0).values_list("pk", flat=True)
    in_progress = patients.filter(
        procedures__status=Procedure.Status.IN_PROGRESS, procedures__voided_at__isnull=True
    ).values_list("pk", flat=True)
    return sorted({*with_balance, *in_progress}, key=str)


class _ServiceMap:
    """Finds the target branch's service of the same name, or adds a hidden copy.

    A copy is inactive so it never appears in the target's price list on its
    own; it only keeps a moved plan line pointing at a row of its own branch.
    """

    def __init__(self, target: Clinic):
        self.target = target
        self.cache = {}

    def __call__(self, service: Service | None) -> Service | None:
        if service is None:
            return None
        if service.pk not in self.cache:
            match = Service.objects.filter(clinic=self.target, name__iexact=service.name).first()
            if match is None:
                match = Service.objects.create(
                    clinic=self.target,
                    name=service.name,
                    code=service.code,
                    price=service.price,
                    duration_minutes=service.duration_minutes,
                    is_active=False,
                )
            self.cache[service.pk] = match
        return self.cache[service.pk]


@transaction.atomic
def move_patients(*, source: Clinic, target: Clinic, patient_ids, doctor: Membership) -> list[Patient]:
    patients = Patient.objects.select_for_update().filter(clinic=source, pk__in=patient_ids)
    found = list(patients)
    if len(found) != len(set(patient_ids)):
        raise ValidationError({"patients": "Invalid pk - object does not exist."}, code="does_not_exist")
    blocked = blocked_patients(Patient.objects.filter(pk__in=[p.pk for p in found]))
    if blocked:
        raise ValidationError(
            {"patients": f"{len(blocked)} patient(s) have a balance or an unfinished procedure."},
            code="not_movable",
        )

    now = timezone.now()
    ids = [p.pk for p in found]
    upcoming = list(
        Appointment.objects.select_related("service").filter(
            patient_id__in=ids, clinic=source, status__in=UPCOMING, start_at__gte=now
        )
    )
    overlap = Q(pk__in=[])
    for appointment in upcoming:
        overlap |= Q(start_at__lt=appointment.end_at, end_at__gt=appointment.start_at)
    if Appointment.objects.filter(overlap, clinic=target, doctor=doctor, status__in=Appointment.BLOCKING).exists():
        raise ValidationError(
            {"doctor": "The doctor already has an appointment at one of these times."}, code="conflict"
        )

    services = _ServiceMap(target)
    for appointment in upcoming:
        appointment.clinic = target
        appointment.doctor = doctor
        appointment.chair = None
        appointment.service = services(appointment.service)
        appointment.save(update_fields=["clinic", "doctor", "chair", "service", "updated_at"])
    # Past visits move too, unless a procedure was billed on them: those stay with the money.
    Appointment.objects.filter(patient_id__in=ids, clinic=source).exclude(procedures__isnull=False).update(
        clinic=target, chair=None, service=None, updated_at=now
    )

    for plan in TreatmentPlan.objects.filter(patient_id__in=ids, clinic=source).prefetch_related("items__service"):
        for item in plan.items.all():
            item.service = services(item.service)
            item.save(update_fields=["service", "updated_at"])
        plan.clinic = target
        if plan.status in OPEN_PLAN:
            plan.doctor = doctor
        plan.save(update_fields=["clinic", "doctor", "updated_at"])

    for model in (Prescription, Attachment, ToothRecord, ToothEvent, MedicalHistory):
        model.objects.filter(patient_id__in=ids, clinic=source).update(clinic=target)
    BotAccount.objects.filter(patient_id__in=ids).update(clinic=target)
    Patient.objects.filter(pk__in=ids).update(clinic=target, primary_doctor=doctor, updated_at=now)
    return found
