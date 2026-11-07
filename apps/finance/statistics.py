"""Counts for the statistics screen: how busy the clinic was, never who came.

Every figure is a count over ids, so nothing here can carry PHI. Days and
hours are the clinic's wall clock: "Monday 10:00" means the chair, not UTC.
"""

from collections import defaultdict

from django.db.models import Count, Q
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate

from apps.dental.models import Procedure, TreatmentPlan
from apps.finance.periods import DateRange
from apps.finance.reports import window
from apps.patients.models import Patient
from apps.scheduling.models import Appointment
from apps.tenancy.models import Membership

Status = Appointment.Status
TOP_SERVICES = 10


def _mine(queryset, doctor):
    return queryset if doctor is None else queryset.filter(doctor=doctor)


def _appointments(clinic_ids, start, end, doctor=None):
    return _mine(Appointment.objects.filter(clinic_id__in=clinic_ids, start_at__gte=start, start_at__lt=end), doctor)


def _procedures(clinic_ids, start, end, doctor=None):
    return _mine(
        Procedure.objects.filter(
            clinic_id__in=clinic_ids, voided_at__isnull=True, performed_at__gte=start, performed_at__lt=end
        ),
        doctor,
    )


def _totals(clinic_ids, period: DateRange, zone, doctor=None) -> dict:
    start, end = window(period, zone)
    appointments = _appointments(clinic_ids, start, end, doctor).aggregate(
        # A cancelled visit never held the chair, so it is not part of the workload.
        total=Count("id", filter=~Q(status=Status.CANCELLED)),
        completed=Count("id", filter=Q(status=Status.COMPLETED)),
        no_show=Count("id", filter=Q(status=Status.NO_SHOW)),
        cancelled=Count("id", filter=Q(status=Status.CANCELLED)),
    )
    procedures = _procedures(clinic_ids, start, end, doctor)

    # Seen = treated, or a visit that was completed; either proves the patient came.
    seen = set(procedures.values_list("patient_id", flat=True))
    seen |= set(
        _appointments(clinic_ids, start, end, doctor)
        .filter(status=Status.COMPLETED)
        .values_list("patient_id", flat=True)
    )
    returning = Patient.objects.filter(pk__in=seen, created_at__lt=start).count()
    new_patients = Patient.objects.filter(clinic_id__in=clinic_ids, created_at__gte=start, created_at__lt=end)
    if doctor is not None:
        # A doctor's new patients are the ones registered to them.
        new_patients = new_patients.filter(primary_doctor=doctor)

    return {
        "appointments": appointments["total"],
        "appointments_completed": appointments["completed"],
        "no_shows": appointments["no_show"],
        "cancellations": appointments["cancelled"],
        "new_patients": new_patients.count(),
        "returning_patients": returning,
        "procedures": procedures.count(),
        "plans_accepted": _mine(
            TreatmentPlan.objects.filter(clinic_id__in=clinic_ids, accepted_at__gte=start, accepted_at__lt=end),
            doctor,
        ).count(),
    }


def statistics_overview(clinic_ids, period: DateRange, zone, *, doctor=None) -> dict:
    """`doctor` narrows every figure to one doctor's work and patients."""
    start, end = window(period, zone)
    appointments = _appointments(clinic_ids, start, end, doctor).exclude(status=Status.CANCELLED)
    procedures = _procedures(clinic_ids, start, end, doctor)

    visits = defaultdict(lambda: {"total": 0, "completed": 0})
    for day, status, count in (
        appointments.annotate(day=TruncDate("start_at", tzinfo=zone))
        .values_list("day", "status")
        .annotate(c=Count("id"))
    ):
        bucket = visits[period.bucket_start(day)]
        bucket["total"] += count
        if status == Status.COMPLETED:
            bucket["completed"] += count

    treated = defaultdict(int)
    for day, count in (
        procedures.annotate(day=TruncDate("performed_at", tzinfo=zone)).values_list("day").annotate(c=Count("id"))
    ):
        treated[period.bucket_start(day)] += count

    doctors = defaultdict(lambda: {"appointments": 0, "appointments_completed": 0, "procedures": 0})
    for doctor_id, status, count in appointments.values_list("doctor_id", "status").annotate(c=Count("id")):
        doctors[doctor_id]["appointments"] += count
        if status == Status.COMPLETED:
            doctors[doctor_id]["appointments_completed"] += count
    for doctor_id, count in procedures.values_list("doctor_id").annotate(c=Count("id")):
        doctors[doctor_id]["procedures"] += count
    members = Membership.objects.filter(pk__in=list(doctors)).select_related("user", "clinic")

    return {
        "from": period.start,
        "to": period.end,
        "bucket": period.bucket,
        "totals": _totals(clinic_ids, period, zone, doctor),
        "previous_totals": _totals(clinic_ids, period.previous(), zone, doctor),
        "appointments_series": [{"start": day, **visits[day]} for day in period.buckets()],
        "procedures_series": [{"start": day, "count": treated[day]} for day in period.buckets()],
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
            key=lambda row: (-row["appointments"], -row["procedures"], row["doctor_name"]),
        ),
        "services": [
            {"service": service_id, "service_name": name, "count": count}
            for service_id, name, count in procedures.values_list("service_id", "service__name")
            .annotate(c=Count("id"))
            .order_by("-c", "service__name")[:TOP_SERVICES]
        ],
        "busy_slots": [
            {"weekday": weekday, "hour": hour, "appointments": count}
            for weekday, hour, count in appointments.annotate(
                weekday=ExtractIsoWeekDay("start_at", tzinfo=zone), hour=ExtractHour("start_at", tzinfo=zone)
            )
            .values_list("weekday", "hour")
            .annotate(c=Count("id"))
            .order_by("weekday", "hour")
        ],
        "teeth": [
            {"tooth": tooth, "count": count}
            for tooth, count in procedures.filter(tooth__isnull=False)
            .values_list("tooth")
            .annotate(c=Count("id"))
            .order_by("tooth")
        ],
    }
