from decimal import Decimal

from apps.catalog.models import Service
from apps.dental.models import Procedure


def charge(world, patient, amount):
    service = Service.objects.create(clinic=patient.clinic, name=f"S{amount}", price=Decimal(amount))
    return Procedure.objects.create(
        clinic=patient.clinic,
        patient=patient,
        doctor=world.doctor_a,
        service=service,
        unit_price=Decimal(amount),
        performed_at="2026-11-01T10:00:00Z",
    )


def pay(client, patient, amount, method="cash"):
    return client.post(
        "/api/v1/payments/", {"patient": str(patient.pk), "amount": amount, "method": method}, format="json"
    )


def test_balance_is_charges_minus_payments(world):
    charge(world, world.patient_a, "500000")
    admin = world.client(world.admin_a)
    assert pay(admin, world.patient_a, "200000").status_code == 201
    body = admin.get(f"/api/v1/balances/{world.patient_a.pk}/").json()
    assert (body["charged"], body["paid"], body["debt"]) == ("500000.00", "200000.00", "300000.00")


def test_debtors_list(world):
    charge(world, world.patient_a, "100")
    admin = world.client(world.admin_a)
    debtors = admin.get("/api/v1/balances/?has_debt=true").json()["results"]
    assert [row["id"] for row in debtors] == [str(world.patient_a.pk)]


def test_voided_payment_does_not_count_and_needs_owner(world):
    charge(world, world.patient_a, "1000")
    admin = world.client(world.admin_a)
    payment = pay(admin, world.patient_a, "1000").json()
    url = f"/api/v1/payments/{payment['id']}/void/"
    assert admin.post(url, {"reason": "Typo"}, format="json").status_code == 403
    owner = world.client(world.owner, clinic=world.branch_a)
    assert owner.post(url, {"reason": "Typo"}, format="json").status_code == 200
    assert admin.get(f"/api/v1/balances/{world.patient_a.pk}/").json()["debt"] == "1000.00"


def test_payments_cannot_be_edited_or_deleted(world):
    admin = world.client(world.admin_a)
    payment = pay(admin, world.patient_a, "10").json()
    url = f"/api/v1/payments/{payment['id']}/"
    assert admin.patch(url, {"amount": "1"}, format="json").status_code in {403, 405}
    assert admin.delete(url).status_code in {403, 405}


def test_doctor_cannot_take_payments_but_sees_own_patient_balance(world):
    doctor = world.client(world.doctor_a)
    assert pay(doctor, world.patient_a, "10").status_code == 403
    assert doctor.get(f"/api/v1/balances/{world.patient_a.pk}/").status_code == 200
    assert doctor.get(f"/api/v1/balances/{world.patient_a2.pk}/").status_code == 404


def test_rejects_zero_and_foreign_patient(world):
    admin = world.client(world.admin_a)
    assert pay(admin, world.patient_a, "0").status_code == 400
    assert pay(admin, world.patient_b, "10").status_code == 400


def test_owner_sees_balances_per_branch_and_combined(world):
    charge(world, world.patient_a, "100")
    charge(world, world.patient_b, "200")
    owner_all = world.client(world.owner, organization=world.org)
    combined = owner_all.get("/api/v1/balances/?has_debt=true").json()["results"]
    assert {row["clinic_name"] for row in combined} == {"Branch A", "Branch B"}
    owner_b = world.client(world.owner, clinic=world.branch_b)
    assert [r["id"] for r in owner_b.get("/api/v1/balances/?has_debt=true").json()["results"]] == [
        str(world.patient_b.pk)
    ]
