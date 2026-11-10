from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.models import Payment
from apps.catalog.models import Service
from apps.clinical.models import Prescription
from apps.dental.models import PlanItem, Procedure, TreatmentPlan
from apps.scheduling.models import Appointment, Chair
from apps.tenancy.models import Membership

from .conftest import ids, make_user


@pytest.fixture
def doctor_b(world):
    return Membership.objects.create(user=make_user("doctor_b"), clinic=world.branch_b, role=Membership.Role.DOCTOR)


def move(world, patients, doctor, *, target=None, caller=None):
    client = world.client(caller or world.owner, clinic=world.branch_a)
    target = target or world.branch_b
    return client.post(
        f"/api/v1/branches/{target.pk}/move-patients/",
        {"patients": [str(p.pk) for p in patients], "doctor": str(doctor.pk)},
        format="json",
    )


def test_target_branch_doctors_are_listed_for_the_owner(world, doctor_b):
    response = world.client(world.owner, clinic=world.branch_a).get(f"/api/v1/branches/{world.branch_b.pk}/doctors/")
    assert response.status_code == 200
    assert ids(response) == {str(doctor_b.pk)}


def test_clinical_record_moves_and_the_new_branch_owns_it(world, doctor_b):
    patient = world.patient_a
    soon = timezone.now() + timedelta(days=2)
    chair = Chair.objects.create(clinic=world.branch_a, name="Chair A")
    filling = Service.objects.create(clinic=world.branch_a, name="Filling", price=Decimal("300000"))
    Service.objects.create(clinic=world.branch_b, name="filling", price=Decimal("320000"))
    future = Appointment.objects.create(
        clinic=world.branch_a,
        patient=patient,
        doctor=world.doctor_a,
        chair=chair,
        service=filling,
        start_at=soon,
        end_at=soon + timedelta(minutes=30),
    )
    prescription = Prescription.objects.create(clinic=world.branch_a, patient=patient, doctor=world.doctor_a)
    plan = TreatmentPlan.objects.create(clinic=world.branch_a, patient=patient, doctor=world.doctor_a, title="Plan")
    PlanItem.objects.create(plan=plan, service=filling, unit_price=Decimal("300000"))

    response = move(world, [patient], doctor_b)
    assert response.status_code == 200, response.json()
    assert response.json() == {"moved": 1}

    patient.refresh_from_db()
    future.refresh_from_db()
    prescription.refresh_from_db()
    plan.refresh_from_db()
    assert patient.clinic == world.branch_b and patient.primary_doctor == doctor_b
    assert future.clinic == world.branch_b and future.doctor == doctor_b and future.chair is None
    assert future.service.clinic == world.branch_b and future.service.name == "filling"
    # A written prescription keeps its author; an open plan is handed to the new doctor.
    assert prescription.clinic == world.branch_b and prescription.doctor == world.doctor_a
    assert plan.clinic == world.branch_b and plan.doctor == doctor_b
    assert plan.items.get().service.clinic == world.branch_b

    assert world.client(world.admin_a).get(f"/api/v1/patients/{patient.pk}/").status_code == 404
    assert world.client(world.admin_b).get(f"/api/v1/patients/{patient.pk}/").status_code == 200
    assert str(patient.pk) in ids(world.client(doctor_b).get("/api/v1/patients/"))


def test_money_stays_in_the_old_branch(world, doctor_b):
    patient = world.patient_a
    service = Service.objects.create(clinic=world.branch_a, name="Crown", price=Decimal("500000"))
    visit_at = timezone.now() - timedelta(days=30)
    visit = Appointment.objects.create(
        clinic=world.branch_a,
        patient=patient,
        doctor=world.doctor_a,
        start_at=visit_at,
        end_at=visit_at + timedelta(minutes=30),
        status=Appointment.Status.COMPLETED,
    )
    procedure = Procedure.objects.create(
        clinic=world.branch_a,
        patient=patient,
        doctor=world.doctor_a,
        service=service,
        unit_price=Decimal("500000"),
        performed_at=visit_at,
        appointment=visit,
    )
    payment = Payment.objects.create(
        clinic=world.branch_a,
        patient=patient,
        amount=Decimal("500000"),
        method="cash",
        paid_at=visit_at,
        received_by=world.admin_a,
    )
    # A crown made with no charge would be odd, but the move must not care.
    unbilled_at = visit_at - timedelta(days=5)
    unbilled = Appointment.objects.create(
        clinic=world.branch_a,
        patient=patient,
        doctor=world.doctor_a,
        start_at=unbilled_at,
        end_at=unbilled_at + timedelta(minutes=30),
        status=Appointment.Status.COMPLETED,
    )

    assert move(world, [patient], doctor_b).status_code == 200

    for row in (procedure, payment, visit, unbilled):
        row.refresh_from_db()
    assert procedure.clinic == world.branch_a and payment.clinic == world.branch_a
    assert visit.clinic == world.branch_a and visit.doctor == world.doctor_a
    assert unbilled.clinic == world.branch_b
    balance = world.client(world.admin_b).get(f"/api/v1/patients/{patient.pk}/").json()
    assert Decimal(balance["debt"]) == 0


def test_patient_with_debt_or_open_work_does_not_move(world, doctor_b):
    service = Service.objects.create(clinic=world.branch_a, name="Root canal", price=Decimal("400000"))
    Procedure.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        service=service,
        unit_price=Decimal("400000"),
        performed_at=timezone.now(),
    )
    response = move(world, [world.patient_a, world.patient_a2], doctor_b)
    assert response.status_code == 400
    assert "patients" in response.json()["errors"]
    world.patient_a2.refresh_from_db()
    assert world.patient_a2.clinic == world.branch_a


def test_unfinished_procedure_blocks_even_when_paid(world, doctor_b):
    service = Service.objects.create(clinic=world.branch_a, name="Implant", price=Decimal("100"))
    Procedure.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        service=service,
        unit_price=Decimal("100"),
        performed_at=timezone.now(),
        status=Procedure.Status.IN_PROGRESS,
    )
    Payment.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        amount=Decimal("100"),
        method="cash",
        paid_at=timezone.now(),
        received_by=world.admin_a,
    )
    assert move(world, [world.patient_a], doctor_b).status_code == 400


def test_target_doctor_must_be_free(world, doctor_b):
    soon = timezone.now() + timedelta(days=1)
    Appointment.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        start_at=soon,
        end_at=soon + timedelta(minutes=30),
    )
    Appointment.objects.create(
        clinic=world.branch_b,
        patient=world.patient_b,
        doctor=doctor_b,
        start_at=soon,
        end_at=soon + timedelta(minutes=30),
    )
    response = move(world, [world.patient_a], doctor_b)
    assert response.status_code == 400
    assert "doctor" in response.json()["errors"]


def test_doctor_must_belong_to_the_target_branch(world):
    response = move(world, [world.patient_a], world.doctor_a2)
    assert response.status_code == 400
    assert "doctor" in response.json()["errors"]


def test_only_patients_of_the_current_branch_move(world, doctor_b):
    response = move(world, [world.patient_other], doctor_b)
    assert response.status_code == 400
    world.patient_other.refresh_from_db()
    assert world.patient_other.clinic == world.other_clinic


def test_cannot_move_to_a_foreign_or_same_branch(world, doctor_b):
    assert move(world, [world.patient_a], doctor_b, target=world.other_clinic).status_code == 404
    assert move(world, [world.patient_a], world.doctor_a, target=world.branch_a).status_code == 400


def test_admin_cannot_move_patients(world, doctor_b):
    assert move(world, [world.patient_a], doctor_b, caller=world.admin_a.user).status_code == 403
