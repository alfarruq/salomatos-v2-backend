def create(world, client):
    response = client.post(
        "/api/v1/prescriptions/",
        {
            "patient": str(world.patient_a.pk),
            "doctor": str(world.doctor_a.pk),
            "items": [{"medicine": "Ibuprofen", "dose": "1", "times_per_day": 2, "duration_days": 3}],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def test_edit_replaces_items_and_notes(world):
    client = world.client(world.doctor_a)
    pk = create(world, client)
    response = client.patch(
        f"/api/v1/prescriptions/{pk}/",
        {
            "notes": "after meals",
            "items": [{"medicine": "Paracetamol", "dose": "1", "times_per_day": 3, "duration_days": 2}],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["notes"] == "after meals"
    assert [item["medicine"] for item in response.json()["items"]] == ["Paracetamol"]


def test_edit_with_an_incomplete_item_is_refused_not_a_500(world):
    client = world.client(world.doctor_a)
    pk = create(world, client)
    response = client.patch(
        f"/api/v1/prescriptions/{pk}/", {"items": [{"medicine": "Paracetamol", "dose": "1"}]}, format="json"
    )
    assert response.status_code == 400


def test_edit_cannot_move_prescription_to_another_patient(world):
    client = world.client(world.admin_a)
    pk = create(world, client)
    response = client.patch(f"/api/v1/prescriptions/{pk}/", {"patient": str(world.patient_a2.pk)}, format="json")
    assert response.status_code == 400


def test_doctor_cannot_hand_own_prescription_to_colleague(world):
    pk = create(world, world.client(world.admin_a))
    response = world.client(world.doctor_a).patch(
        f"/api/v1/prescriptions/{pk}/", {"doctor": str(world.doctor_a2.pk)}, format="json"
    )
    assert response.status_code == 403


def test_admin_may_correct_the_prescribing_doctor(world):
    client = world.client(world.admin_a)
    pk = create(world, client)
    response = client.patch(f"/api/v1/prescriptions/{pk}/", {"doctor": str(world.doctor_a2.pk)}, format="json")
    assert response.status_code == 200, response.json()


def test_delete_and_colleague_cannot_reach_it(world):
    pk = create(world, world.client(world.doctor_a))
    assert world.client(world.doctor_a2).delete(f"/api/v1/prescriptions/{pk}/").status_code == 404
    assert world.client(world.doctor_a).delete(f"/api/v1/prescriptions/{pk}/").status_code == 204
