from decimal import Decimal

import pytest

from apps.catalog.models import Service
from apps.dental.models import PlanItem, ToothEvent, TreatmentPlan


@pytest.fixture
def services(world):
    return {
        "filling": Service.objects.create(clinic=world.branch_a, name="Filling", price=Decimal("300000")),
        "crown": Service.objects.create(clinic=world.branch_a, name="Crown", price=Decimal("1500000")),
        "foreign": Service.objects.create(clinic=world.branch_b, name="Filling B", price=Decimal("1")),
    }


def make_plan(client, world, services, items=None):
    items = items or [
        {"service": str(services["filling"].pk), "tooth": 36, "surfaces": ["O", "D"]},
        {"service": str(services["crown"].pk), "tooth": 46, "discount_percent": "10"},
    ]
    return client.post(
        "/api/v1/treatment-plans/",
        {"patient": str(world.patient_a.pk), "title": "Lower molars", "items": items},
        format="json",
    )


# Dental chart


def test_chart_upsert_keeps_history(world):
    client = world.client(world.doctor_a)
    payload = {"patient": str(world.patient_a.pk), "tooth": 36, "condition": "caries", "surfaces": ["O"]}
    assert client.post("/api/v1/tooth-records/", payload, format="json").status_code == 201
    payload["condition"] = "filled"
    second = client.post("/api/v1/tooth-records/", payload, format="json")
    assert second.status_code == 200
    chart = client.get(f"/api/v1/tooth-records/?patient={world.patient_a.pk}").json()
    assert [(row["tooth"], row["condition"]) for row in chart] == [(36, "filled")]
    history = client.get(f"/api/v1/tooth-records/history/?patient={world.patient_a.pk}").json()
    assert [e["condition"] for e in history["results"]] == ["filled", "caries"]


def test_chart_rejects_bad_tooth_and_surface(world):
    client = world.client(world.doctor_a)
    bad_tooth = {"patient": str(world.patient_a.pk), "tooth": 29, "condition": "caries"}
    bad_surface = {"patient": str(world.patient_a.pk), "tooth": 11, "condition": "caries", "surfaces": ["X"]}
    assert client.post("/api/v1/tooth-records/", bad_tooth, format="json").status_code == 400
    assert client.post("/api/v1/tooth-records/", bad_surface, format="json").status_code == 400


def test_chart_of_hidden_patient_is_closed(world):
    client = world.client(world.doctor_a)
    payload = {"patient": str(world.patient_a2.pk), "tooth": 11, "condition": "caries"}
    assert client.post("/api/v1/tooth-records/", payload, format="json").status_code == 400
    history = client.get(f"/api/v1/tooth-records/history/?patient={world.patient_a2.pk}").json()
    assert history["results"] == []
    assert not ToothEvent.objects.exists()


# Treatment plans


def test_plan_prices_come_from_service_and_total_applies_discount(world, services):
    response = make_plan(world.client(world.doctor_a), world, services)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["doctor"] == str(world.doctor_a.pk)
    assert body["status"] == "draft"
    assert body["total"] == "1650000.00"  # 300000 + 1500000 * 0.9


def test_plan_rejects_foreign_service(world, services):
    response = make_plan(world.client(world.admin_a), world, services, items=[{"service": str(services["foreign"].pk)}])
    assert response.status_code == 400


def test_admin_must_name_the_doctor(world, services):
    assert make_plan(world.client(world.admin_a), world, services).status_code == 400


def test_plan_lifecycle_locks_after_accept(world, services):
    client = world.client(world.doctor_a)
    plan_id = make_plan(client, world, services).json()["id"]
    assert client.post(f"/api/v1/treatment-plans/{plan_id}/present/").json()["status"] == "presented"
    assert client.post(f"/api/v1/treatment-plans/{plan_id}/accept/").json()["status"] == "accepted"
    assert client.patch(f"/api/v1/treatment-plans/{plan_id}/", {"title": "x"}, format="json").status_code == 400
    assert client.delete(f"/api/v1/treatment-plans/{plan_id}/").status_code == 400
    assert client.post(f"/api/v1/treatment-plans/{plan_id}/cancel/").json()["status"] == "cancelled"
    assert set(PlanItem.objects.filter(plan_id=plan_id).values_list("status", flat=True)) == {"cancelled"}


# Procedures


def accepted_plan(client, world, services):
    plan_id = make_plan(client, world, services).json()["id"]
    client.post(f"/api/v1/treatment-plans/{plan_id}/accept/")
    return TreatmentPlan.objects.get(pk=plan_id)


def test_performing_every_item_completes_the_plan(world, services):
    client = world.client(world.doctor_a)
    plan = accepted_plan(client, world, services)
    for item in plan.items.all():
        response = client.post(
            "/api/v1/procedures/",
            {"patient": str(world.patient_a.pk), "service": str(item.service_id), "plan_item": str(item.pk)},
            format="json",
        )
        assert response.status_code == 201, response.json()
    plan.refresh_from_db()
    assert plan.status == TreatmentPlan.Status.COMPLETED
    totals = sorted(row["total"] for row in client.get("/api/v1/procedures/").json()["results"])
    assert totals == ["1350000.00", "300000.00"]


def test_plan_item_cannot_be_done_twice_or_for_another_patient(world, services):
    client = world.client(world.admin_a)
    plan = accepted_plan(world.client(world.doctor_a), world, services)
    item = plan.items.first()
    payload = {
        "patient": str(world.patient_a.pk),
        "doctor": str(world.doctor_a.pk),
        "service": str(item.service_id),
        "plan_item": str(item.pk),
    }
    other = {**payload, "patient": str(world.patient_a2.pk)}
    assert client.post("/api/v1/procedures/", other, format="json").status_code == 400
    assert client.post("/api/v1/procedures/", payload, format="json").status_code == 201
    assert client.post("/api/v1/procedures/", payload, format="json").status_code == 400


def test_procedure_money_is_immutable_and_void_reopens_item(world, services):
    doctor = world.client(world.doctor_a)
    plan = accepted_plan(doctor, world, services)
    item = plan.items.first()
    created = doctor.post(
        "/api/v1/procedures/",
        {"patient": str(world.patient_a.pk), "service": str(item.service_id), "plan_item": str(item.pk)},
        format="json",
    ).json()
    url = f"/api/v1/procedures/{created['id']}/"
    doctor.patch(url, {"unit_price": "1", "notes": "ok"}, format="json")
    assert doctor.get(url).json()["unit_price"] == created["unit_price"]
    assert doctor.post(url + "void/", {"reason": "Wrong tooth"}, format="json").status_code == 403
    admin = world.client(world.admin_a)
    assert admin.post(url + "void/", {"reason": "Wrong tooth"}, format="json").status_code == 200
    item.refresh_from_db()
    assert item.status == PlanItem.Status.PLANNED


def test_owner_sees_procedures_of_all_branches(world, services):
    doctor = world.client(world.doctor_a)
    doctor.post(
        "/api/v1/procedures/",
        {"patient": str(world.patient_a.pk), "service": str(services["filling"].pk)},
        format="json",
    )
    owner = world.client(world.owner, organization=world.org)
    rows = owner.get("/api/v1/procedures/").json()["results"]
    assert len(rows) == 1
    assert rows[0]["patient_name"] == world.patient_a.full_name
    assert world.client(world.admin_b).get("/api/v1/procedures/").json()["results"] == []


# Procedure status


def test_procedure_is_completed_unless_started_in_progress(world, services):
    doctor = world.client(world.doctor_a)
    base = {"patient": str(world.patient_a.pk), "service": str(services["filling"].pk), "tooth": 36}
    done = doctor.post("/api/v1/procedures/", base, format="json").json()
    assert done["status"] == "completed"
    assert done["completed_at"] == done["performed_at"]
    started = doctor.post("/api/v1/procedures/", {**base, "status": "in_progress"}, format="json").json()
    assert started["status"] == "in_progress"
    assert started["completed_at"] is None
    rows = doctor.get(f"/api/v1/procedures/?patient={world.patient_a.pk}&status=in_progress").json()["results"]
    assert [row["id"] for row in rows] == [started["id"]]


def test_in_progress_charge_is_owed_and_cannot_be_completed_by_patch(world, services):
    doctor = world.client(world.doctor_a)
    created = doctor.post(
        "/api/v1/procedures/",
        {"patient": str(world.patient_a.pk), "service": str(services["crown"].pk), "status": "in_progress"},
        format="json",
    ).json()
    url = f"/api/v1/procedures/{created['id']}/"
    doctor.patch(url, {"status": "completed"}, format="json")
    assert doctor.get(url).json()["status"] == "in_progress"
    balance = world.client(world.admin_a).get(f"/api/v1/balances/{world.patient_a.pk}/").json()
    assert balance["debt"] == "1500000.00"


def test_complete_moves_status_and_closes_plan_item(world, services):
    doctor = world.client(world.doctor_a)
    plan = accepted_plan(doctor, world, services)
    item = plan.items.first()
    created = doctor.post(
        "/api/v1/procedures/",
        {
            "patient": str(world.patient_a.pk),
            "service": str(item.service_id),
            "plan_item": str(item.pk),
            "status": "in_progress",
        },
        format="json",
    ).json()
    item.refresh_from_db()
    assert item.status == PlanItem.Status.PLANNED
    url = f"/api/v1/procedures/{created['id']}/complete/"
    response = doctor.post(url)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["completed_at"] is not None
    item.refresh_from_db()
    assert item.status == PlanItem.Status.DONE
    assert doctor.post(url).status_code == 400


def test_complete_is_own_work_and_not_after_void(world, services):
    created = (
        world.client(world.doctor_a)
        .post(
            "/api/v1/procedures/",
            {"patient": str(world.patient_a.pk), "service": str(services["filling"].pk), "status": "in_progress"},
            format="json",
        )
        .json()
    )
    url = f"/api/v1/procedures/{created['id']}/"
    admin = world.client(world.admin_a)
    assert admin.post(url + "void/", {"reason": "Wrong patient"}, format="json").status_code == 200
    assert admin.post(url + "complete/").status_code == 400
    assert world.client(world.admin_b).post(url + "complete/").status_code == 404


def test_doctor_cannot_complete_a_colleagues_procedure(world, services):
    created = (
        world.client(world.admin_a)
        .post(
            "/api/v1/procedures/",
            {
                "patient": str(world.patient_a2.pk),
                "doctor": str(world.doctor_a2.pk),
                "service": str(services["filling"].pk),
                "status": "in_progress",
            },
            format="json",
        )
        .json()
    )
    url = f"/api/v1/procedures/{created['id']}/complete/"
    assert world.client(world.doctor_a).post(url).status_code in (403, 404)
    assert world.client(world.doctor_a2).post(url).status_code == 200
