from datetime import UTC, datetime, timedelta

import pytest

from apps.dental.models import Procedure, TreatmentPlan
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from .test_finance import owner_of, procedure

URL = "/api/v1/reports/statistics/?from=2026-10-01&to=2026-10-31"
Status = Appointment.Status


def visit(world, at, *, status=Status.SCHEDULED, doctor=None, patient=None):
    patient = patient or world.patient_a
    start = datetime.fromisoformat(at)
    return Appointment.objects.create(
        clinic=patient.clinic,
        patient=patient,
        doctor=doctor or world.doctor_a,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=status,
    )


def registered(patient, at):
    Patient.objects.filter(pk=patient.pk).update(created_at=datetime.fromisoformat(at))


@pytest.fixture
def october(world):
    registered(world.patient_a, "2026-05-01T09:00:00+00:00")
    registered(world.patient_a2, "2026-10-12T09:00:00+00:00")
    # Tashkent is UTC+5: 05:00Z is Tuesday 10:00 at the chair.
    visit(world, "2026-10-06T05:00:00+00:00", status=Status.COMPLETED)
    visit(world, "2026-10-06T05:30:00+00:00", status=Status.NO_SHOW, doctor=world.doctor_a2)
    visit(world, "2026-10-13T05:00:00+00:00", status=Status.CANCELLED)
    visit(world, "2026-10-20T06:00:00+00:00", patient=world.patient_a2, doctor=world.doctor_a2)
    # 31 Oct 20:00Z is already 1 Nov in Tashkent: next month.
    visit(world, "2026-10-31T20:00:00+00:00")
    filling = procedure(world, at="2026-10-06T05:20:00Z")
    Procedure.objects.filter(pk=filling.pk).update(tooth=36)
    procedure(world, patient=world.patient_a2, doctor=world.doctor_a2, amount="500", at="2026-10-20T06:10:00Z")
    procedure(world, at="2026-09-15T06:00:00Z")
    TreatmentPlan.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        title="Plan",
        status=TreatmentPlan.Status.ACCEPTED,
        accepted_at=datetime(2026, 10, 7, 6, tzinfo=UTC),
    )


def test_statistics_totals(world, october):
    body = owner_of(world).get(URL).json()

    assert body["totals"] == {
        "appointments": 3,
        "appointments_completed": 1,
        "no_shows": 1,
        "cancellations": 1,
        "new_patients": 1,
        # Patient A was registered in May and treated in October; A2 is new.
        "returning_patients": 1,
        "procedures": 2,
        "plans_accepted": 1,
    }
    assert body["previous_totals"]["procedures"] == 1
    assert body["bucket"] == "day"
    assert len(body["appointments_series"]) == 31
    assert sum(point["total"] for point in body["appointments_series"]) == 3
    assert sum(point["count"] for point in body["procedures_series"]) == 2


def test_statistics_breakdowns(world, october):
    body = owner_of(world).get(URL).json()

    doctors = {row["doctor"]: row for row in body["doctors"]}
    assert doctors[str(world.doctor_a.pk)] == {
        "doctor": str(world.doctor_a.pk),
        "doctor_name": world.doctor_a.user.full_name,
        "clinic_name": "Branch A",
        "appointments": 1,
        "appointments_completed": 1,
        "procedures": 1,
    }
    assert (doctors[str(world.doctor_a2.pk)]["appointments"], doctors[str(world.doctor_a2.pk)]["procedures"]) == (2, 1)
    assert {(slot["weekday"], slot["hour"]): slot["appointments"] for slot in body["busy_slots"]} == {
        (2, 10): 2,
        (2, 11): 1,
    }
    assert body["teeth"] == [{"tooth": 36, "count": 1}]
    assert sorted(row["count"] for row in body["services"]) == [1, 1]


def test_statistics_carry_no_patient_data(world, october):
    text = owner_of(world).get(URL).content.decode()

    for patient in (world.patient_a, world.patient_a2):
        assert patient.full_name not in text
        assert patient.phone_number not in text
        assert str(patient.pk) not in text


def test_statistics_access_and_isolation(world, october):
    assert world.client(world.doctor_a).get(URL).status_code == 403
    assert world.client(world.admin_a).get(URL).json()["totals"]["appointments"] == 3
    assert world.client(world.admin_b).get(URL).json()["totals"]["appointments"] == 0
    assert world.client(world.other_admin).get(URL).json()["totals"]["procedures"] == 0
    # A branch of someone else's organization is not found, whatever the role.
    assert world.client(world.other_admin, clinic=world.branch_a).get(URL).status_code == 404

    visit(world, "2026-10-08T05:00:00+00:00", patient=world.patient_b, doctor=world.admin_b)
    combined = world.client(world.owner, organization=world.org).get(URL).json()
    assert combined["totals"]["appointments"] == 4


@pytest.mark.parametrize(
    "query", ["", "?from=2026-10-01", "?from=2026-10-31&to=2026-10-01", "?from=2025-01-01&to=2026-10-01"]
)
def test_statistics_rejects_a_bad_range(world, query):
    response = owner_of(world).get("/api/v1/reports/statistics/" + query)
    assert response.status_code == 400
