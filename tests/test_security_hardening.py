"""Regressions for the 2026-11-09 security review."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.throttles import LoginUsernameThrottle
from apps.audit.models import AuditLog
from apps.catalog.models import Service
from apps.dental.models import Procedure
from apps.tenancy.models import Membership

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "An0ther-Str0ng-pass!"


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()
    yield
    cache.clear()


def owner_of(world, clinic):
    return Membership.objects.get(user=world.owner, clinic=clinic)


def login(username, password=PASSWORD, **extra):
    return APIClient().post("/api/v1/auth/login/", {"username": username, "password": password}, format="json", **extra)


def test_doctor_cannot_book_a_colleagues_patient(world):
    api = world.client(world.doctor_a)
    start = (timezone.now() + timedelta(days=1)).isoformat()
    body = {"patient": str(world.patient_a2.pk), "doctor": str(world.doctor_a.pk), "start_at": start}
    assert api.post("/api/v1/appointments/", body, format="json").status_code == 400
    # The failed booking must not have opened the record either.
    assert api.get(f"/api/v1/patients/{world.patient_a2.pk}/").status_code == 404


def test_doctor_cannot_move_a_booking_to_a_colleagues_patient(world):
    api = world.client(world.doctor_a)
    start = (timezone.now() + timedelta(days=1)).isoformat()
    body = {"patient": str(world.patient_a.pk), "doctor": str(world.doctor_a.pk), "start_at": start}
    appointment = api.post("/api/v1/appointments/", body, format="json").json()["id"]
    r = api.patch(f"/api/v1/appointments/{appointment}/", {"patient": str(world.patient_a2.pk)}, format="json")
    assert r.status_code == 400


def test_admin_still_books_any_patient(world):
    api = world.client(world.admin_a)
    start = (timezone.now() + timedelta(days=1)).isoformat()
    body = {"patient": str(world.patient_a2.pk), "doctor": str(world.doctor_a.pk), "start_at": start}
    assert api.post("/api/v1/appointments/", body, format="json").status_code == 201


def test_doctor_cannot_hand_a_plan_to_a_colleague(world):
    api = world.client(world.doctor_a)
    plan = api.post("/api/v1/treatment-plans/", {"patient": str(world.patient_a.pk), "title": "Plan"}, format="json")
    r = api.patch(f"/api/v1/treatment-plans/{plan.json()['id']}/", {"doctor": str(world.doctor_a2.pk)}, format="json")
    assert r.status_code == 403


def test_login_limit_ignores_forged_forwarded_for(world):
    codes = [login("owner", "wrong", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code for i in range(12)]
    assert 429 in codes


def test_login_limit_follows_the_username(world, monkeypatch):
    monkeypatch.setattr(LoginUsernameThrottle, "THROTTLE_RATES", {"login_username": "3/hour"})
    codes = [login("owner", "wrong", REMOTE_ADDR=f"10.0.0.{i}").status_code for i in range(4)]
    assert codes[-1] == 429
    # Another account is not held back by guesses at this one.
    assert login("admin_a", REMOTE_ADDR="10.0.0.9").status_code == 200


def test_password_change_signs_out_other_sessions(world):
    tokens = login("doctor_a").json()["result"]
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    body = {"old_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert api.post("/api/v1/auth/change-password/", body, format="json").status_code == 204
    r = APIClient().post("/api/v1/auth/refresh/", {"refresh_token": tokens["refresh_token"]}, format="json")
    assert r.status_code == 401


def test_owner_reset_of_staff_password_signs_them_out(world):
    tokens = login("doctor_a").json()["result"]
    api = world.client(owner_of(world, world.branch_a))
    assert (
        api.patch(f"/api/v1/staff/{world.doctor_a.pk}/", {"password": NEW_PASSWORD}, format="json").status_code == 200
    )
    r = APIClient().post("/api/v1/auth/refresh/", {"refresh_token": tokens["refresh_token"]}, format="json")
    assert r.status_code == 401


def test_owner_cannot_change_a_login_shared_with_another_organization(world):
    Membership.objects.create(user=world.doctor_a.user, clinic=world.other_clinic, role=Membership.Role.ADMIN)
    api = world.client(owner_of(world, world.branch_a))
    url = f"/api/v1/staff/{world.doctor_a.pk}/"
    assert api.patch(url, {"password": NEW_PASSWORD}, format="json").status_code == 403
    assert api.patch(url, {"username": "taken_over"}, format="json").status_code == 403
    # Clinic-side fields of the membership stay editable.
    assert api.patch(url, {"experience_years": 5}, format="json").status_code == 200
    assert login("doctor_a").status_code == 200


def test_upload_type_comes_from_the_extension(world):
    api = world.client(world.admin_a)
    upload = SimpleUploadedFile("x.png", b"<script>alert(1)</script>", content_type="text/html")
    r = api.post(
        "/api/v1/attachments/",
        {"patient": str(world.patient_a.pk), "kind": "photo", "file": upload},
        format="multipart",
    )
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/png"
    assert api.get(f"/api/v1/attachments/{r.json()['id']}/download/")["Content-Type"] == "image/png"


def test_patient_list_and_search_are_audited(world):
    api = world.client(world.admin_a)
    api.get("/api/v1/patients/")
    api.post("/api/v1/patients/search/", {"query": "Patient"}, format="json")
    viewed = AuditLog.objects.filter(action=AuditLog.Action.VIEW, target_type="patients.patient")
    assert set(viewed.values_list("target_id", flat=True)) == {world.patient_a.pk, world.patient_a2.pk}


def test_schema_is_not_public_outside_debug(world):
    assert APIClient().get("/api/schema/").status_code == 404


def test_deleting_a_used_service_is_a_clear_400(world):
    service = Service.objects.create(clinic=world.branch_a, name="Filling", price=100)
    Procedure.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        service=service,
        unit_price=100,
        performed_at=timezone.now(),
    )
    r = world.client(owner_of(world, world.branch_a)).delete(f"/api/v1/services/{service.pk}/")
    assert r.status_code == 400
    assert r.json()["message_key"] == "in_use"


def test_malformed_id_in_a_query_is_a_400(world):
    r = world.client(world.admin_a).get("/api/v1/tooth-records/history/?patient=abc")
    assert r.status_code == 400
