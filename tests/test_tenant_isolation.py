from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog

from .conftest import ids


def test_unauthenticated_is_rejected(world):
    response = APIClient().get("/api/v1/patients/", HTTP_X_CLINIC_ID=str(world.branch_a.pk))
    assert response.status_code == 401


def test_clinic_header_is_required(world):
    client = world.client(world.admin_a.user)
    assert client.get("/api/v1/patients/").status_code == 400


def test_foreign_clinic_header_looks_like_missing_clinic(world):
    client = world.client(world.admin_a, clinic=world.other_clinic)
    assert client.get("/api/v1/patients/").status_code == 404


def test_branch_admin_sees_only_own_branch(world):
    client = world.client(world.admin_a)
    assert ids(client.get("/api/v1/patients/")) == {str(world.patient_a.pk), str(world.patient_a2.pk)}
    assert client.get(f"/api/v1/patients/{world.patient_b.pk}/").status_code == 404
    assert client.get(f"/api/v1/patients/{world.patient_other.pk}/").status_code == 404


def test_other_branch_admin_cannot_use_all_branches_mode(world):
    client = world.client(world.admin_a.user, organization=world.org)
    assert client.get("/api/v1/patients/").status_code == 404


def test_foreign_patient_id_is_rejected_on_write(world):
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/",
        {"patient": str(world.patient_b.pk), "doctor": str(world.doctor_a.pk), "start_at": start.isoformat()},
        format="json",
    )
    assert response.status_code == 400
    assert "patient" in response.json()["errors"]


def test_foreign_doctor_id_is_rejected(world):
    client = world.client(world.admin_a)
    response = client.patch(
        f"/api/v1/patients/{world.patient_a.pk}/", {"primary_doctor": str(world.admin_b.pk)}, format="json"
    )
    assert response.status_code == 400


def test_doctor_sees_only_own_patients(world):
    client = world.client(world.doctor_a)
    assert ids(client.get("/api/v1/patients/")) == {str(world.patient_a.pk)}
    assert client.get(f"/api/v1/patients/{world.patient_a2.pk}/").status_code == 404


def test_doctor_cannot_book_for_colleague(world):
    client = world.client(world.doctor_a)
    start = timezone.now() + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/",
        {"patient": str(world.patient_a.pk), "doctor": str(world.doctor_a2.pk), "start_at": start.isoformat()},
        format="json",
    )
    assert response.status_code == 403


def test_doctor_cannot_attach_records_to_hidden_patient(world):
    client = world.client(world.doctor_a)
    response = client.post(
        "/api/v1/prescriptions/",
        {
            "patient": str(world.patient_a2.pk),
            "items": [{"medicine": "Ibuprofen", "dose": "400 mg", "times_per_day": 2, "duration_days": 3}],
        },
        format="json",
    )
    assert response.status_code == 400


def test_owner_all_branches_mode_reads_every_branch(world):
    client = world.client(world.owner, organization=world.org)
    response = client.get("/api/v1/patients/")
    assert response.status_code == 200
    assert ids(response) == {str(world.patient_a.pk), str(world.patient_a2.pk), str(world.patient_b.pk)}
    assert {row["clinic_name"] for row in response.json()["results"]} == {"Branch A", "Branch B"}


def test_owner_all_branches_mode_is_read_only(world):
    client = world.client(world.owner, organization=world.org)
    response = client.post("/api/v1/patients/", {"full_name": "X", "phone_number": "+998901112233"}, format="json")
    assert response.status_code == 400


def test_owner_can_work_in_a_single_branch(world):
    client = world.client(world.owner, clinic=world.branch_b)
    assert ids(client.get("/api/v1/patients/")) == {str(world.patient_b.pk)}


def test_new_branch_is_visible_to_owner(world):
    from apps.tenancy.models import Clinic, Membership

    branch_c = Clinic.objects.create(organization=world.org, name="Branch C")
    assert Membership.objects.filter(user=world.owner, clinic=branch_c, role=Membership.Role.OWNER).exists()


def test_reading_a_patient_is_audited(world):
    client = world.client(world.admin_a)
    client.get(f"/api/v1/patients/{world.patient_a.pk}/")
    log = AuditLog.objects.get(action=AuditLog.Action.VIEW, target_id=world.patient_a.pk)
    assert log.actor == world.admin_a.user
    assert log.clinic == world.branch_a
