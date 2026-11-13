"""People who only book a visit (leads) stay out of the patient list until their first procedure."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.catalog.models import Service
from apps.patients.leads import archive_stale_leads
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from .conftest import ids

PHONE = "+998901112233"


def book_new(client, world, start=None, doctor=None, **extra):
    start = start or timezone.now() + timedelta(days=1)
    payload = {
        "new_patient": {"full_name": "Walk In", "phone_number": PHONE},
        "doctor": str((doctor or world.doctor_a).pk),
        "start_at": start.isoformat(),
        **extra,
    }
    return client.post("/api/v1/appointments/", payload, format="json")


@pytest.fixture
def lead(world):
    response = book_new(world.client(world.admin_a), world)
    assert response.status_code == 201, response.json()
    return Patient.objects.get(pk=response.json()["patient"])


@pytest.fixture
def service(world):
    return Service.objects.create(clinic=world.branch_a, name="Filling", price=Decimal("100000"))


def test_booking_a_new_person_creates_a_lead(world, lead):
    assert lead.is_lead
    assert lead.clinic == world.branch_a
    assert lead.full_name == "Walk In"
    assert AuditLog.objects.filter(target_id=lead.pk, action=AuditLog.Action.CREATE).exists()


def test_lead_is_hidden_from_patient_list_and_default_search(world, lead):
    client = world.client(world.admin_a)
    assert str(lead.pk) not in ids(client.get("/api/v1/patients/"))
    assert str(lead.pk) in ids(client.get("/api/v1/patients/?lead=true"))
    assert str(lead.pk) not in ids(client.post("/api/v1/patients/search/", {"query": "Walk"}, format="json"))
    found = client.post("/api/v1/patients/search/", {"query": "Walk", "include_leads": True}, format="json")
    assert str(lead.pk) in ids(found)


def test_lead_detail_is_readable_and_flagged(world, lead):
    body = world.client(world.admin_a).get(f"/api/v1/patients/{lead.pk}/").json()
    assert body["is_lead"] is True
    assert body["registered_at"] is None


def test_patient_and_new_patient_are_exclusive(world):
    client = world.client(world.admin_a)
    response = book_new(client, world, patient=str(world.patient_a.pk))
    assert response.status_code == 400
    assert "new_patient" in response.json()["errors"]


def test_booking_needs_some_patient(world):
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/",
        {"doctor": str(world.doctor_a.pk), "start_at": start.isoformat()},
        format="json",
    )
    assert response.status_code == 400
    assert "patient" in response.json()["errors"]


def test_new_patient_phone_is_validated(world):
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/",
        {
            "new_patient": {"full_name": "X", "phone_number": "abc"},
            "doctor": str(world.doctor_a.pk),
            "start_at": start.isoformat(),
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Patient.objects.filter(full_name="X").exists()


def test_failed_booking_leaves_no_lead_behind(world):
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    assert book_new(client, world, start=start).status_code == 201
    # Same doctor, same slot: refused, and the second lead must not be kept.
    assert book_new(client, world, start=start).status_code == 400
    assert Patient.objects.filter(phone_number=PHONE).count() == 1


def test_doctor_can_book_a_lead_and_then_sees_it(world):
    client = world.client(world.doctor_a)
    response = book_new(client, world)
    assert response.status_code == 201
    patient_id = response.json()["patient"]
    assert client.get(f"/api/v1/patients/{patient_id}/").status_code == 200
    # The colleague who is not booked with this person does not see them.
    assert world.client(world.doctor_a2).get(f"/api/v1/patients/{patient_id}/").status_code == 404


def test_lead_lands_in_header_clinic_only(world):
    client = world.client(world.admin_b)
    response = book_new(client, world, doctor=None)
    # doctor_a works in branch A, so branch B cannot book with them.
    assert response.status_code == 400
    assert not Patient.objects.filter(phone_number=PHONE).exists()


def test_first_procedure_on_a_lead_is_refused(world, lead, service):
    client = world.client(world.admin_a)
    response = client.post(
        "/api/v1/procedures/",
        {"patient": str(lead.pk), "doctor": str(world.doctor_a.pk), "service": str(service.pk)},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["errors"]["patient"] == "lead"


def test_register_turns_lead_into_patient(world, lead, service):
    client = world.client(world.admin_a)
    response = client.post(
        f"/api/v1/patients/{lead.pk}/register/",
        {"birth_date": "1990-05-01", "gender": "male", "address": "Tashkent"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["is_lead"] is False
    lead.refresh_from_db()
    assert lead.registered_at is not None
    assert str(lead.birth_date) == "1990-05-01"
    assert str(lead.pk) in ids(client.get("/api/v1/patients/"))
    procedure = client.post(
        "/api/v1/procedures/",
        {"patient": str(lead.pk), "doctor": str(world.doctor_a.pk), "service": str(service.pk)},
        format="json",
    )
    assert procedure.status_code == 201, procedure.json()


def test_register_validates_like_the_patient_form(world, lead):
    client = world.client(world.admin_a)
    response = client.post(f"/api/v1/patients/{lead.pk}/register/", {"phone_number": "abc"}, format="json")
    assert response.status_code == 400
    lead.refresh_from_db()
    assert lead.is_lead


def test_register_isolation(world, lead):
    # Other clinic -> 404, a role that cannot manage patients is covered by required_permissions.
    other = world.client(world.other_admin)
    assert other.post(f"/api/v1/patients/{lead.pk}/register/", {}, format="json").status_code == 404
    branch_b = world.client(world.admin_b)
    assert branch_b.post(f"/api/v1/patients/{lead.pk}/register/", {}, format="json").status_code == 404
    lead.refresh_from_db()
    assert lead.is_lead


def test_existing_patients_count_as_registered(world):
    assert not world.patient_a.is_lead


def test_stale_leads_are_archived_not_deleted(world, lead):
    now = timezone.now()
    # Booking is still ahead: kept.
    assert archive_stale_leads(now=now + timedelta(days=5)) == 0
    Appointment.objects.filter(patient=lead).update(
        start_at=now - timedelta(days=11), end_at=now - timedelta(days=11) + timedelta(minutes=30)
    )
    Patient.objects.filter(pk=lead.pk).update(created_at=now - timedelta(days=12))
    assert archive_stale_leads(now=now) == 1
    lead.refresh_from_db()
    assert lead.archived_at is not None
    assert Appointment.objects.filter(patient=lead).exists()
    assert AuditLog.objects.filter(target_id=lead.pk, action=AuditLog.Action.ARCHIVE).exists()
    # Registered patients are never touched, however old.
    Patient.objects.filter(pk=world.patient_a.pk).update(created_at=now - timedelta(days=400))
    assert archive_stale_leads(now=now) == 0


def test_lead_with_recent_booking_is_kept(world, lead):
    now = timezone.now()
    Patient.objects.filter(pk=lead.pk).update(created_at=now - timedelta(days=30))
    Appointment.objects.filter(patient=lead).update(
        start_at=now - timedelta(days=3), end_at=now - timedelta(days=3) + timedelta(minutes=30)
    )
    assert archive_stale_leads(now=now) == 0


def test_leads_are_not_counted_as_new_patients(world, lead):
    today = timezone.localdate()
    response = world.client(world.owner, clinic=world.branch_a).get(
        f"/api/v1/reports/statistics/?from={today}&to={today}"
    )
    assert response.status_code == 200, response.json()
    # patient_a and patient_a2 from the fixture, not the lead.
    assert response.json()["totals"]["new_patients"] == 2
