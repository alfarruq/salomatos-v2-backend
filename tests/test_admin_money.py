from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.models import Payment
from apps.catalog.models import Service
from apps.dental.models import Procedure

FULL = {"money:view", "payment:view", "patient:debt"}


@pytest.fixture
def crown(world):
    return Service.objects.create(clinic=world.branch_a, name="Crown", price=Decimal("1500000"))


@pytest.fixture
def work(world, crown):
    """A charged procedure with a part payment: 1 500 000 charged, 500 000 paid."""
    Procedure.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        doctor=world.doctor_a,
        service=crown,
        unit_price=Decimal("1500000"),
        performed_at=timezone.now(),
    )
    Payment.objects.create(
        clinic=world.branch_a,
        patient=world.patient_a,
        amount=Decimal("500000"),
        received_by=world.admin_a,
        paid_at=timezone.now(),
    )


def owner(world):
    return world.client(world.owner, clinic=world.branch_a)


def permissions(world, user):
    return set(world.client(user).get("/api/v1/auth/me/").json()["memberships"][0]["permissions"])


def set_admin(world, **fields):
    response = owner(world).patch(f"/api/v1/staff/{world.admin_a.pk}/", fields, format="json")
    assert response.status_code == 200, response.json()


def set_clinic(world, value):
    assert owner(world).patch("/api/v1/clinic/", {"admins_see_money": value}, format="json").status_code == 200


def test_admin_sees_everything_in_patients_and_treatments_by_default(world, work):
    assert FULL <= permissions(world, world.admin_a)
    admin = world.client(world.admin_a)
    row = admin.get("/api/v1/procedures/").json()["results"][0]
    assert row["unit_price"] == "1500000.00"
    assert admin.get(f"/api/v1/patients/{world.patient_a.pk}/").json()["debt"] == "1000000.00"
    assert admin.get(f"/api/v1/balances/{world.patient_a.pk}/").json()["paid"] == "500000.00"
    assert admin.get(f"/api/v1/payments/?patient={world.patient_a.pk}").status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/payments/", "/api/v1/balances/?has_debt=true"])
def test_the_moliya_lists_are_never_open_to_an_admin(world, work, path):
    assert world.client(world.admin_a).get(path).status_code == 403
    assert owner(world).get(path).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/expenses/",
        "/api/v1/recurring-expenses/",
        "/api/v1/payroll/?month=2026-10",
        "/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31",
    ],
)
def test_the_rest_of_moliya_is_the_owners(world, path):
    assert world.client(world.admin_a).get(path).status_code == 403


def test_debts_only_shows_what_is_owed_and_nothing_else(world, work):
    set_admin(world, debts_only=True)
    admin = world.client(world.admin_a)
    assert permissions(world, world.admin_a) & FULL == {"patient:debt"}
    row = admin.get("/api/v1/procedures/").json()["results"][0]
    assert (row["unit_price"], row["total"]) == (None, None)
    assert admin.get(f"/api/v1/patients/{world.patient_a.pk}/").json()["debt"] == "1000000.00"
    assert admin.get(f"/api/v1/balances/{world.patient_a.pk}/").status_code == 403
    assert admin.get(f"/api/v1/payments/?patient={world.patient_a.pk}").status_code == 403


def test_switched_off_admin_sees_no_money_not_even_debt(world, work):
    set_admin(world, can_see_money=False)
    admin = world.client(world.admin_a)
    assert not FULL & permissions(world, world.admin_a)
    assert admin.get("/api/v1/procedures/").json()["results"][0]["unit_price"] is None
    assert admin.get(f"/api/v1/patients/{world.patient_a.pk}/").json()["debt"] is None


def test_the_clinic_switch_overrides_each_admin(world, work):
    set_admin(world, can_see_money=True, debts_only=False)
    set_clinic(world, False)
    assert not FULL & permissions(world, world.admin_a)
    assert world.client(world.admin_a).get(f"/api/v1/patients/{world.patient_a.pk}/").json()["debt"] is None
    set_clinic(world, True)
    assert FULL <= permissions(world, world.admin_a)


def test_the_switch_is_per_admin_and_per_branch(world, work):
    set_admin(world, can_see_money=False)
    assert FULL <= permissions(world, world.admin_b)


def test_a_desk_line_takes_the_price_list_figure_without_money(world, crown):
    set_admin(world, debts_only=True)
    body = {
        "patient": str(world.patient_a.pk),
        "service": str(crown.pk),
        "doctor": str(world.doctor_a.pk),
        "tooth": 46,
        "unit_price": "1",
        "paid_amount": "1",
    }
    assert world.client(world.admin_a).post("/api/v1/procedures/", body, format="json").status_code == 201
    assert Procedure.objects.get().unit_price == Decimal("1500000")
    assert not Payment.objects.exists()


def test_only_the_owner_flips_admin_switches(world):
    admin = world.client(world.admin_a)
    url = f"/api/v1/staff/{world.admin_a.pk}/"
    assert admin.patch(url, {"debts_only": True}, format="json").status_code == 403
    assert admin.patch("/api/v1/clinic/", {"admins_see_money": True}, format="json").status_code == 403


def take_payment(client, world, amount="1000"):
    return client.post(
        "/api/v1/payments/", {"patient": str(world.patient_a.pk), "amount": amount, "method": "cash"}, format="json"
    )


@pytest.mark.parametrize("fields", [{"can_see_money": False}, {"debts_only": True}])
def test_an_admin_takes_payments_whatever_the_switches(world, work, fields):
    set_admin(world, **fields)
    admin = world.client(world.admin_a)
    assert take_payment(admin, world).status_code == 201
    # Taking money is not reading the ledger.
    assert admin.get(f"/api/v1/payments/?patient={world.patient_a.pk}").status_code == 403


def test_the_clinic_switch_does_not_stop_an_admin_taking_payments(world, work):
    set_clinic(world, False)
    assert take_payment(world.client(world.admin_a), world).status_code == 201


def test_a_doctor_takes_payments_even_when_money_is_hidden(world, work):
    assert owner(world).patch("/api/v1/clinic/", {"doctors_see_money": False}, format="json").status_code == 200
    doctor = world.client(world.doctor_a)
    assert take_payment(doctor, world).status_code == 201
    assert doctor.get("/api/v1/payments/").status_code == 403
    # Only for patients the doctor can see.
    other = {"patient": str(world.patient_a2.pk), "amount": "1", "method": "cash"}
    assert doctor.post("/api/v1/payments/", other, format="json").status_code == 400
