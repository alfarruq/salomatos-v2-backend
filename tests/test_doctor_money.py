from decimal import Decimal

import pytest

from apps.billing.models import Payment
from apps.catalog.models import Service
from apps.dental.models import Procedure

MONEY = {"money:view", "payment:view", "payroll:view_own"}


@pytest.fixture
def crown(world):
    return Service.objects.create(clinic=world.branch_a, name="Crown", price=Decimal("1500000"))


def permissions(world, user):
    body = world.client(user).get("/api/v1/auth/me/").json()
    return set(body["memberships"][0]["permissions"])


def record(world, crown, **extra):
    body = {"patient": str(world.patient_a.pk), "service": str(crown.pk), "tooth": 46, **extra}
    return world.client(world.doctor_a).post("/api/v1/procedures/", body, format="json")


def hide_from_doctor_a(world):
    url = f"/api/v1/staff/{world.doctor_a.pk}/"
    response = world.client(world.owner, clinic=world.branch_a).patch(url, {"can_see_money": False}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["can_see_money"] is False


def hide_from_all_doctors(world):
    api = world.client(world.owner, clinic=world.branch_a)
    response = api.patch("/api/v1/clinic/", {"doctors_see_money": False}, format="json")
    assert response.status_code == 200, response.json()


def test_doctors_see_money_by_default(world, crown):
    assert MONEY <= permissions(world, world.doctor_a)
    assert record(world, crown).json()["unit_price"] == "1500000.00"


@pytest.mark.parametrize("hide", [hide_from_doctor_a, hide_from_all_doctors])
def test_hidden_money_is_removed_on_the_server_but_debt_stays(world, crown, hide):
    record(world, crown)
    hide(world)
    doctor = world.client(world.doctor_a)

    assert not MONEY & permissions(world, world.doctor_a)
    row = doctor.get("/api/v1/procedures/").json()["results"][0]
    assert (row["unit_price"], row["total"]) == (None, None)
    assert doctor.get(f"/api/v1/services/{crown.pk}/").json()["price"] is None
    assert doctor.get("/api/v1/payments/").status_code == 403
    assert doctor.get("/api/v1/balances/").status_code == 403
    assert doctor.get("/api/v1/me/earnings/").status_code == 403
    # Only the debt is left for the doctor.
    assert doctor.get(f"/api/v1/patients/{world.patient_a.pk}/").json()["debt"] == "1500000.00"


def test_hidden_money_doctor_cannot_price_a_line_or_take_a_payment(world, crown):
    hide_from_doctor_a(world)
    response = record(world, crown, unit_price="1", paid_amount="1")
    assert response.status_code == 201, response.json()
    assert Procedure.objects.get().unit_price == Decimal("1500000")
    assert not Payment.objects.exists()


def test_the_switch_is_per_doctor(world, crown):
    hide_from_doctor_a(world)
    assert MONEY <= permissions(world, world.doctor_a2)


def test_admins_and_owners_are_never_affected(world, crown):
    hide_from_all_doctors(world)
    assert MONEY - {"payroll:view_own"} <= permissions(world, world.admin_a)
    assert world.client(world.admin_a).get("/api/v1/payments/").status_code == 200


def test_only_the_owner_flips_the_switches(world):
    doctor = world.client(world.doctor_a)
    assert (
        doctor.patch(f"/api/v1/staff/{world.doctor_a.pk}/", {"can_see_money": True}, format="json").status_code == 403
    )
    assert doctor.patch("/api/v1/clinic/", {"doctors_see_money": True}, format="json").status_code == 403
    admin = world.client(world.admin_a)
    assert (
        admin.patch(f"/api/v1/staff/{world.doctor_a.pk}/", {"can_see_money": False}, format="json").status_code == 403
    )
