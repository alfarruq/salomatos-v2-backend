"""What each kind of bot user may read. Plain queries, so tests need no Telegram.

A patient reads only their own rows; a doctor only their own day; an owner the
branches of organizations they own. The account decides, never the message.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Q, Sum

from apps.billing.balance import PROCEDURE_TOTAL, annotate_balance
from apps.billing.models import Payment
from apps.bot.models import AppointmentReminder
from apps.clinical.models import Prescription
from apps.dental.models import Procedure
from apps.finance.periods import start_of
from apps.imaging.models import Attachment
from apps.patients.models import Patient
from apps.scheduling.models import Appointment
from apps.tenancy.models import Clinic, Membership

Status = Appointment.Status
# Booked for today and not yet over: the doctor still has to see them.
WAITING = (Status.SCHEDULED, Status.CONFIRMED, Status.ARRIVED, Status.IN_CHAIR)
RECENT = 10
# The evening before, patients are reminded from this local hour on.
EVENING_FROM = 18
ZERO = Decimal("0")


def zone_of(clinic: Clinic) -> ZoneInfo:
    return ZoneInfo(clinic.timezone)


def today_in(clinic: Clinic) -> date:
    return datetime.now(zone_of(clinic)).date()


def _day_window(clinic: Clinic, day: date) -> tuple[datetime, datetime]:
    zone = zone_of(clinic)
    return start_of(day, zone), start_of(day + timedelta(days=1), zone)


# Patient


def patient_prescriptions(patient: Patient):
    return (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items")
        .order_by("-created_at")[:RECENT]
    )


def patient_prescription(patient: Patient, prescription_id) -> Prescription | None:
    # Filtered by the patient, so a forged callback cannot open someone else's.
    return Prescription.objects.filter(patient=patient, pk=prescription_id).select_related("clinic").first()


def patient_attachments(patient: Patient):
    return Attachment.objects.filter(patient=patient).order_by("-created_at")[:RECENT]


def patient_procedures(patient: Patient):
    return (
        Procedure.objects.filter(patient=patient, voided_at__isnull=True)
        .select_related("service", "doctor__user")
        .order_by("-performed_at")[:20]
    )


def patient_doctor(patient: Patient) -> Membership | None:
    if patient.primary_doctor_id is None:
        return None
    return Membership.objects.select_related("user", "specialty", "clinic").get(pk=patient.primary_doctor_id)


# Doctor


@dataclass
class DoctorDay:
    clinic: Clinic
    day: date
    new_patients: int
    procedures: int
    waiting: list = field(default_factory=list)
    appointments: int = 0


def doctor_memberships(user):
    return Membership.objects.filter(user=user, role=Membership.Role.DOCTOR, is_active=True).select_related("clinic")


def doctor_day(doctor: Membership, day: date | None = None) -> DoctorDay:
    clinic = doctor.clinic
    day = day or today_in(clinic)
    start, end = _day_window(clinic, day)
    appointments = Appointment.objects.filter(doctor=doctor, start_at__gte=start, start_at__lt=end)
    return DoctorDay(
        clinic=clinic,
        day=day,
        new_patients=Patient.objects.filter(primary_doctor=doctor, created_at__gte=start, created_at__lt=end).count(),
        procedures=Procedure.objects.filter(
            doctor=doctor, voided_at__isnull=True, performed_at__gte=start, performed_at__lt=end
        ).count(),
        waiting=list(appointments.filter(status__in=WAITING).select_related("patient", "service").order_by("start_at")),
        appointments=appointments.exclude(status=Status.CANCELLED).count(),
    )


# Owner


@dataclass
class BranchDay:
    clinic: Clinic
    new_patients: int
    procedures: int
    procedures_sum: Decimal
    collected: Decimal
    debt: Decimal
    appointments: int
    appointments_completed: int
    appointments_waiting: int


def owned_clinics(user):
    return Clinic.objects.filter(organization__owners=user, organization__is_active=True, is_active=True).order_by(
        "name"
    )


def branch_day(clinic: Clinic, day: date) -> BranchDay:
    start, end = _day_window(clinic, day)
    procedures = Procedure.objects.filter(
        clinic=clinic, voided_at__isnull=True, performed_at__gte=start, performed_at__lt=end
    ).aggregate(count=Count("id"), total=Sum(PROCEDURE_TOTAL))
    appointments = Appointment.objects.filter(clinic=clinic, start_at__gte=start, start_at__lt=end).aggregate(
        total=Count("id", filter=~Q(status=Status.CANCELLED)),
        completed=Count("id", filter=Q(status=Status.COMPLETED)),
        waiting=Count("id", filter=Q(status__in=WAITING)),
    )
    collected = Payment.objects.filter(
        clinic=clinic, voided_at__isnull=True, paid_at__gte=start, paid_at__lt=end
    ).aggregate(s=Sum("amount"))["s"]
    # Overpayments are credit, not negative debt, so only what is owed counts.
    debt = annotate_balance(Patient.objects.filter(clinic=clinic)).filter(debt__gt=0).aggregate(s=Sum("debt"))["s"]
    return BranchDay(
        clinic=clinic,
        new_patients=Patient.objects.filter(clinic=clinic, created_at__gte=start, created_at__lt=end).count(),
        procedures=procedures["count"],
        procedures_sum=procedures["total"] or ZERO,
        collected=collected or ZERO,
        debt=debt or ZERO,
        appointments=appointments["total"],
        appointments_completed=appointments["completed"],
        appointments_waiting=appointments["waiting"],
    )


def owner_day(user, day: date | None = None) -> tuple[date | None, list[BranchDay]]:
    clinics = list(owned_clinics(user))
    if not clinics:
        return None, []
    day = day or today_in(clinics[0])
    return day, [branch_day(clinic, day) for clinic in clinics]


# Appointment reminders

REMIND_AHEAD = timedelta(hours=2)
# Below this, a reminder would arrive when the patient is already on the way.
REMIND_MIN = timedelta(minutes=30)
REMINDABLE = (Status.SCHEDULED, Status.CONFIRMED)


def reminder_candidates(now: datetime) -> list[tuple[Appointment, str]]:
    """Visits that are due a reminder now, for patients who linked the bot.

    "Day before" means the visit is on the next calendar day in the clinic's own
    zone and it is already evening there. A visit booked less than
    two hours ahead gets no two-hour reminder: the booking was the reminder.
    """
    kinds = AppointmentReminder.Kind
    visits = (
        Appointment.objects.filter(
            status__in=REMINDABLE,
            start_at__gt=now + REMIND_MIN,
            start_at__lte=now + timedelta(hours=48),
            patient__archived_at__isnull=True,
            patient__bot_account__telegram_chat_id__isnull=False,
        )
        .select_related("clinic", "doctor__user", "patient__bot_account")
        .order_by("start_at")
    )
    due = []
    for visit in visits:
        zone = zone_of(visit.clinic)
        local_now = now.astimezone(zone)
        tomorrow = local_now.date() + timedelta(days=1)
        if visit.start_at.astimezone(zone).date() == tomorrow and local_now.hour >= EVENING_FROM:
            due.append((visit, kinds.DAY_BEFORE))
        if visit.start_at <= now + REMIND_AHEAD and visit.created_at <= visit.start_at - REMIND_AHEAD:
            due.append((visit, kinds.TWO_HOURS))
    return due
