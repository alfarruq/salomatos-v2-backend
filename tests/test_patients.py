from .conftest import ids


def test_search_by_name_uses_post_body(world):
    client = world.client(world.admin_a)
    response = client.post("/api/v1/patients/search/", {"query": "a2"}, format="json")
    assert response.status_code == 200
    assert ids(response) == {str(world.patient_a2.pk)}


def test_query_string_search_is_not_supported(world):
    # A name in the URL would land in access logs; the list ignores it.
    client = world.client(world.admin_a)
    assert len(ids(client.get("/api/v1/patients/?search=A2"))) == 2


def test_patients_cannot_be_deleted(world):
    client = world.client(world.admin_a)
    assert client.delete(f"/api/v1/patients/{world.patient_a.pk}/").status_code in {403, 405}
    world.patient_a.refresh_from_db()


def test_archive_hides_from_list_and_restore_brings_back(world):
    client = world.client(world.admin_a)
    assert client.post(f"/api/v1/patients/{world.patient_a.pk}/archive/").status_code == 200
    assert str(world.patient_a.pk) not in ids(client.get("/api/v1/patients/"))
    assert str(world.patient_a.pk) in ids(client.get("/api/v1/patients/?archived=true"))
    client.post(f"/api/v1/patients/{world.patient_a.pk}/restore/")
    assert str(world.patient_a.pk) in ids(client.get("/api/v1/patients/"))


def test_doctor_cannot_archive(world):
    client = world.client(world.doctor_a)
    assert client.post(f"/api/v1/patients/{world.patient_a.pk}/archive/").status_code == 403


def test_medical_history_roundtrip(world):
    client = world.client(world.doctor_a)
    url = f"/api/v1/patients/{world.patient_a.pk}/medical-history/"
    assert client.patch(url, {"allergies": "Lidocaine"}, format="json").status_code == 200
    assert client.get(url).json()["allergies"] == "Lidocaine"


def test_created_patient_belongs_to_header_clinic(world):
    client = world.client(world.admin_a)
    response = client.post(
        "/api/v1/patients/",
        {"full_name": "New", "phone_number": "+998901234567", "clinic": str(world.other_clinic.pk)},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["clinic"] == str(world.branch_a.pk)


def test_search_matches_words_in_any_order(world):
    api = world.client(world.admin_a)
    response = api.post("/api/v1/patients/search/", {"query": "A2 Patient"}, format="json")
    assert {row["id"] for row in response.json()["results"]} == {str(world.patient_a2.pk)}


def test_search_matches_a_phone_typed_with_spaces(world):
    api = world.client(world.admin_a)
    response = api.post("/api/v1/patients/search/", {"query": "90 000 00 02"}, format="json")
    assert {row["id"] for row in response.json()["results"]} == {str(world.patient_a2.pk)}
