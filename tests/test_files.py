import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.imaging.models import Attachment


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def upload(client, world, name="Ali_Valiyev_xray.png"):
    return client.post(
        "/api/v1/attachments/",
        {
            "patient": str(world.patient_a.pk),
            "kind": "xray",
            "tooth": 36,
            "file": SimpleUploadedFile(name, b"\x89PNG fake", content_type="image/png"),
        },
        format="multipart",
    )


def test_upload_renames_file_and_download_needs_scope(world):
    response = upload(world.client(world.doctor_a), world)
    assert response.status_code == 201, response.json()
    attachment = Attachment.objects.get(pk=response.json()["id"])
    assert "Valiyev" not in attachment.file.name

    url = f"/api/v1/attachments/{attachment.pk}/download/"
    assert world.client(world.doctor_a).get(url).status_code == 200
    assert world.client(world.doctor_a2).get(url).status_code == 404
    assert world.client(world.admin_b).get(url).status_code == 404


def test_invalid_tooth_is_rejected(world):
    client = world.client(world.admin_a)
    response = client.post(
        "/api/v1/attachments/",
        {
            "patient": str(world.patient_a.pk),
            "kind": "xray",
            "tooth": 19,
            "file": SimpleUploadedFile("a.png", b"x", content_type="image/png"),
        },
        format="multipart",
    )
    assert response.status_code == 400


def test_media_is_not_served_by_url(world, client):
    assert client.get("/media/clinics/x.png").status_code == 404


def test_prescription_pdf(world):
    client = world.client(world.doctor_a)
    created = client.post(
        "/api/v1/prescriptions/",
        {
            "patient": str(world.patient_a.pk),
            "items": [{"medicine": "Ibuprofen", "dose": "400 mg", "times_per_day": 2, "duration_days": 3}],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    response = client.get(f"/api/v1/prescriptions/{created.json()['id']}/pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "Patient" not in response["Content-Disposition"]
