from datetime import datetime, timedelta

from django.utils import timezone

from apps.scheduling.models import Chair


def book(client, world, start, doctor=None, chair=None, minutes=30, status=None):
    payload = {
        "patient": str(world.patient_a.pk),
        "doctor": str((doctor or world.doctor_a).pk),
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=minutes)).isoformat(),
    }
    if chair:
        payload["chair"] = str(chair.pk)
    if status:
        payload["status"] = status
    return client.post("/api/v1/appointments/", payload, format="json")


def test_doctor_double_booking_is_rejected(world):
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    assert book(client, world, start).status_code == 201
    response = book(client, world, start + timedelta(minutes=15))
    assert response.status_code == 400
    assert "doctor" in response.json()["errors"]


def test_chair_double_booking_is_rejected(world):
    chair = Chair.objects.create(clinic=world.branch_a, name="1")
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    assert book(client, world, start, chair=chair).status_code == 201
    response = book(client, world, start, doctor=world.doctor_a2, chair=chair)
    assert response.status_code == 400
    assert "chair" in response.json()["errors"]


def test_back_to_back_and_cancelled_do_not_conflict(world):
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    assert book(client, world, start, status="cancelled").status_code == 201
    assert book(client, world, start).status_code == 201
    assert book(client, world, start + timedelta(minutes=30)).status_code == 201


def test_end_defaults_from_service_duration(world):
    from apps.catalog.models import Service

    service = Service.objects.create(clinic=world.branch_a, name="Filling", price=100, duration_minutes=45)
    client = world.client(world.admin_a)
    start = timezone.now() + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/",
        {
            "patient": str(world.patient_a.pk),
            "doctor": str(world.doctor_a.pk),
            "service": str(service.pk),
            "start_at": start.isoformat(),
        },
        format="json",
    )
    assert response.status_code == 201
    end = datetime.fromisoformat(response.json()["end_at"])
    assert abs(end - (start + timedelta(minutes=45))) < timedelta(seconds=1)
