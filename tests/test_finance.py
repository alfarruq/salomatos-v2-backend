from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.models import Payment
from apps.catalog.models import Service
from apps.dental.models import Procedure
from apps.finance.allocation import allocate
from apps.finance.periods import add_months
from apps.tenancy.models import Membership

from .conftest import ids


def owner_of(world, clinic=None):
    return world.client(world.owner, clinic=clinic or world.branch_a)


def expense(client, **fields):
    body = {"category": "rent", "amount": "1000000", "method": "transfer", "spent_on": "2026-10-05", **fields}
    return client.post("/api/v1/expenses/", body, format="json")


def procedure(world, *, doctor=None, patient=None, amount="1000000", at="2026-10-10T07:00:00Z"):
    patient = patient or world.patient_a
    service = Service.objects.create(clinic=patient.clinic, name=f"S{amount}", price=Decimal(amount))
    return Procedure.objects.create(
        clinic=patient.clinic,
        patient=patient,
        doctor=doctor or world.doctor_a,
        service=service,
        unit_price=Decimal(amount),
        performed_at=at,
    )


def payment(world, *, patient=None, amount="1000000", at="2026-10-10T08:00:00Z", method="cash"):
    patient = patient or world.patient_a
    return Payment.objects.create(
        clinic=patient.clinic,
        patient=patient,
        amount=Decimal(amount),
        method=method,
        paid_at=at,
        received_by=world.admin_a,
    )


def terms(world, *, doctor=None, percent="30", fixed="0", base="collected", month="2026-10", clinic=None):
    return owner_of(world, clinic).post(
        "/api/v1/compensations/",
        {
            "doctor": str((doctor or world.doctor_a).pk),
            "percent": percent,
            "fixed": fixed,
            "base": base,
            "effective_from": month,
        },
        format="json",
    )


def payroll_row(client, month, doctor):
    body = client.get(f"/api/v1/payroll/?month={month}").json()
    return next(row for row in body["rows"] if row["doctor"] == str(doctor.pk))


# --- Expenses -----------------------------------------------------------------


def test_admin_records_an_expense(world):
    admin = world.client(world.admin_a)
    response = expense(admin, payee="Landlord")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["category"], body["amount"], body["created_by"]) == ("rent", "1000000.00", str(world.admin_a.pk))
    assert body["clinic"] == str(world.branch_a.pk)


def test_expense_cannot_be_edited_or_deleted(world):
    admin = world.client(world.admin_a)
    url = f"/api/v1/expenses/{expense(admin).json()['id']}/"
    assert admin.patch(url, {"amount": "1"}, format="json").status_code in {403, 405}
    assert admin.delete(url).status_code in {403, 405}


def test_void_needs_owner_and_a_reason(world):
    admin = world.client(world.admin_a)
    url = f"/api/v1/expenses/{expense(admin).json()['id']}/void/"
    assert admin.post(url, {"reason": "Typo"}, format="json").status_code == 403
    owner = owner_of(world)
    assert owner.post(url, {}, format="json").status_code == 400
    voided = owner.post(url, {"reason": "Typo"}, format="json")
    assert voided.status_code == 200 and voided.json()["voided_at"] is not None
    assert owner.post(url, {"reason": "Again"}, format="json").json()["errors"] == {}  # already voided


def test_future_expense_is_refused(world):
    admin = world.client(world.admin_a)
    tomorrow = (timezone.localdate() + timedelta(days=2)).isoformat()
    assert expense(admin, spent_on=tomorrow).status_code == 400


def test_doctor_has_no_access_to_expenses(world):
    doctor = world.client(world.doctor_a)
    assert doctor.get("/api/v1/expenses/").status_code == 403
    assert expense(doctor).status_code == 403


def test_pay_categories_are_owner_only(world):
    admin = world.client(world.admin_a)
    refused = expense(admin, category="staff_salary")
    assert refused.status_code == 400 and refused.json()["errors"] == {"category": "forbidden"}

    owner = owner_of(world)
    salary = expense(owner, category="staff_salary", payee="Receptionist").json()
    rent = expense(admin).json()
    assert ids(admin.get("/api/v1/expenses/")) == {rent["id"]}
    assert admin.get(f"/api/v1/expenses/{salary['id']}/").status_code == 404
    assert ids(owner.get("/api/v1/expenses/")) == {rent["id"], salary["id"]}


def test_doctor_share_needs_a_doctor_of_this_branch(world):
    owner = owner_of(world)
    missing = expense(owner, category="doctor_share")
    assert missing.json()["errors"] == {"doctor": "required"}
    foreign = expense(owner, category="doctor_share", doctor=str(world.admin_b.pk))
    assert foreign.status_code == 400
    not_a_doctor = expense(owner, category="doctor_share", doctor=str(world.admin_a.pk))
    assert not_a_doctor.status_code == 400
    ok = expense(owner, category="doctor_share", doctor=str(world.doctor_a.pk))
    assert ok.status_code == 201 and ok.json()["period"] == "2026-10"
    assert expense(owner, doctor=str(world.doctor_a.pk)).json()["errors"] == {"doctor": "invalid"}


def test_expenses_are_isolated_per_branch(world):
    rent_a = expense(world.client(world.admin_a)).json()
    admin_b = world.client(world.admin_b)
    assert admin_b.get(f"/api/v1/expenses/{rent_a['id']}/").status_code == 404
    assert world.client(world.other_admin).get(f"/api/v1/expenses/{rent_a['id']}/").status_code == 404
    owner_all = world.client(world.owner, organization=world.org)
    expense(admin_b, amount="5")
    assert {row["clinic_name"] for row in owner_all.get("/api/v1/expenses/").json()["results"]} == {
        "Branch A",
        "Branch B",
    }
    assert expense(owner_all).json()["errors"] == {"clinic": "clinic_required"}


def test_summary_groups_by_kind_and_skips_voided(world):
    admin = world.client(world.admin_a)
    owner = owner_of(world)
    expense(admin, category="rent", amount="300", spent_on="2026-10-01")
    expense(admin, category="materials", amount="200", spent_on="2026-10-20")
    expense(owner, category="staff_salary", amount="500", spent_on="2026-10-25")
    expense(admin, category="rent", amount="100", spent_on="2026-09-15")
    voided = expense(admin, category="lab", amount="999", spent_on="2026-10-02").json()
    owner.post(f"/api/v1/expenses/{voided['id']}/void/", {"reason": "Typo"}, format="json")

    owner_view = owner.get("/api/v1/expenses/summary/?from=2026-10-01&to=2026-10-31").json()
    assert owner_view["totals"] == {
        "total": "1000.00",
        "count": 3,
        "payroll": "500.00",
        "fixed": "300.00",
        "variable": "200.00",
    }
    assert owner_view["previous_totals"]["total"] == "100.00"
    assert owner_view["bucket"] == "day" and len(owner_view["series"]) == 31
    assert owner_view["by_category"][0] == {"category": "staff_salary", "amount": "500.00"}

    admin_view = admin.get("/api/v1/expenses/summary/?from=2026-10-01&to=2026-10-31").json()
    assert admin_view["totals"]["total"] == "500.00" and admin_view["totals"]["payroll"] == "0.00"


@pytest.mark.parametrize(
    "query",
    ["", "from=2026-10-01", "from=2026-10-31&to=2026-10-01", "from=2025-01-01&to=2026-10-01", "from=x&to=y"],
)
def test_summary_rejects_a_bad_range(world, query):
    assert world.client(world.admin_a).get(f"/api/v1/expenses/summary/?{query}").status_code == 400


# --- Recurring ----------------------------------------------------------------


def template(client, **fields):
    body = {"name": "Rent", "category": "rent", "amount": "2000000", "method": "transfer", "day_of_month": 5, **fields}
    return client.post("/api/v1/recurring-expenses/", body, format="json")


def this_month():
    return timezone.localdate().replace(day=1)


def test_recurring_month_is_paid_once(world):
    admin = world.client(world.admin_a)
    rent = template(admin).json()
    month = this_month().strftime("%Y-%m")
    pay_url = f"/api/v1/recurring-expenses/{rent['id']}/pay/"

    paid = admin.post(pay_url, {"month": month, "amount": "1900000"}, format="json")
    assert paid.status_code == 201, paid.json()
    assert (paid.json()["category"], paid.json()["amount"], paid.json()["period"]) == ("rent", "1900000.00", month)
    again = admin.post(pay_url, {"month": month}, format="json")
    assert again.json()["errors"] == {"month": "already_paid"}

    due = admin.get(f"/api/v1/recurring-expenses/due/?month={month}").json()
    assert [item["status"] for item in due["items"]] == ["paid"]
    assert due["totals"] == {"expected": "2000000.00", "paid": "1900000.00", "remaining": "0.00"}

    # Voiding the payment frees the slot again.
    owner_of(world).post(f"/api/v1/expenses/{paid.json()['id']}/void/", {"reason": "Wrong amount"}, format="json")
    assert admin.post(pay_url, {"month": month}, format="json").status_code == 201


def test_recurring_due_and_skip(world):
    admin = world.client(world.admin_a)
    rent = template(admin, day_of_month=28).json()
    next_month = add_months(this_month(), 1).strftime("%Y-%m")
    due = admin.get(f"/api/v1/recurring-expenses/due/?month={next_month}").json()
    assert [item["status"] for item in due["items"]] == ["due"]
    assert due["totals"]["remaining"] == "2000000.00"

    url = f"/api/v1/recurring-expenses/{rent['id']}/"
    assert admin.post(url + "skip/", {"month": next_month, "reason": "Holiday"}, format="json").status_code == 204
    due = admin.get(f"/api/v1/recurring-expenses/due/?month={next_month}").json()
    assert [(item["status"], item["skip_reason"]) for item in due["items"]] == [("skipped", "Holiday")]
    assert due["totals"]["expected"] == "0.00"
    assert admin.post(url + "pay/", {"month": next_month}, format="json").json()["errors"] == {"month": "skipped"}

    assert admin.post(url + "unskip/", {"month": next_month}, format="json").status_code == 204
    assert admin.get(f"/api/v1/recurring-expenses/due/?month={next_month}").json()["items"][0]["status"] == "due"


def test_recurring_month_before_the_template_is_empty(world):
    admin = world.client(world.admin_a)
    template(admin)
    last_month = add_months(this_month(), -1).strftime("%Y-%m")
    assert admin.get(f"/api/v1/recurring-expenses/due/?month={last_month}").json()["items"] == []


def test_inactive_template_is_kept_but_not_due(world):
    admin = world.client(world.admin_a)
    rent = template(admin).json()
    assert admin.delete(f"/api/v1/recurring-expenses/{rent['id']}/").status_code in {403, 405}
    switched = admin.patch(f"/api/v1/recurring-expenses/{rent['id']}/", {"is_active": False}, format="json")
    assert switched.status_code == 200
    month = this_month().strftime("%Y-%m")
    assert admin.get(f"/api/v1/recurring-expenses/due/?month={month}").json()["items"] == []


def test_recurring_rules(world):
    admin = world.client(world.admin_a)
    assert template(admin, category="doctor_share").json()["errors"] == {"category": "invalid"}
    assert template(admin, category="staff_salary").json()["errors"] == {"category": "forbidden"}
    assert template(admin, day_of_month=31).status_code == 400
    assert admin.get("/api/v1/recurring-expenses/due/?month=2026-13").status_code == 400
    owner_salary = template(owner_of(world), name="Nurse", category="staff_salary").json()
    assert admin.get(f"/api/v1/recurring-expenses/{owner_salary['id']}/").status_code == 404
    rent_a = template(admin).json()
    assert world.client(world.admin_b).get(f"/api/v1/recurring-expenses/{rent_a['id']}/").status_code == 404


# --- Allocation and payroll -----------------------------------------------------


def test_payments_pay_the_oldest_work_first(world):
    procedure(world, doctor=world.doctor_a, amount="600", at="2026-10-01T07:00:00Z")
    procedure(world, doctor=world.doctor_a2, amount="400", at="2026-10-02T07:00:00Z")
    payment(world, amount="800", at="2026-10-03T07:00:00Z")
    result = allocate([world.branch_a.pk], timezone.now())
    by_doctor = {}
    for row in result:
        by_doctor[row.doctor_id] = by_doctor.get(row.doctor_id, 0) + row.amount
    assert by_doctor == {world.doctor_a.pk: Decimal("600"), world.doctor_a2.pk: Decimal("200")}


def test_advance_payment_counts_when_the_work_is_done(world):
    payment(world, amount="500", at="2026-09-20T07:00:00Z")
    procedure(world, amount="500", at="2026-10-04T07:00:00Z")
    [row] = allocate([world.branch_a.pk], timezone.now())
    assert row.at.date() == date(2026, 10, 4)


def test_payroll_accrues_a_share_of_collected_money(world):
    assert terms(world, percent="30").status_code == 201
    procedure(world, amount="1000000", at="2026-10-10T07:00:00Z")
    payment(world, amount="400000", at="2026-10-11T07:00:00Z")
    payment(world, amount="600000", at="2026-11-02T07:00:00Z")
    owner = owner_of(world)

    october = payroll_row(owner, "2026-10", world.doctor_a)
    assert (october["billed"], october["collected"], october["accrued"]) == ("1000000.00", "400000.00", "120000.00")
    assert october["compensation"]["percent"] == "30.00"

    payout = owner.post(
        "/api/v1/payroll/pay/",
        {
            "doctor": str(world.doctor_a.pk),
            "month": "2026-10",
            "amount": "100000",
            "method": "cash",
            "spent_on": "2026-10-31",
        },
        format="json",
    )
    assert payout.status_code == 201, payout.json()
    assert payout.json()["category"] == "doctor_share"
    assert payroll_row(owner, "2026-10", world.doctor_a)["balance"] == "20000.00"

    november = payroll_row(owner, "2026-11", world.doctor_a)
    assert (november["opening"], november["collected"], november["accrued"], november["balance"]) == (
        "20000.00",
        "600000.00",
        "180000.00",
        "200000.00",
    )


def test_payroll_terms_change_from_their_month(world):
    terms(world, percent="10", fixed="1000", month="2026-09")
    terms(world, percent="50", base="billed", month="2026-10")
    procedure(world, amount="1000", at="2026-09-10T07:00:00Z")
    procedure(world, amount="2000", at="2026-10-10T07:00:00Z")
    owner = owner_of(world)
    september = payroll_row(owner, "2026-09", world.doctor_a)
    assert (september["base_amount"], september["accrued"]) == ("0.00", "1000.00")  # nothing collected
    october = payroll_row(owner, "2026-10", world.doctor_a)
    assert (october["base_amount"], october["accrued"], october["opening"]) == ("2000.00", "1000.00", "1000.00")


def test_payroll_month_follows_the_clinic_clock(world):
    terms(world, percent="100", base="billed")
    # 01:00 on 1 November in Tashkent, still 31 October in UTC.
    procedure(world, amount="700", at="2026-10-31T20:00:00Z")
    owner = owner_of(world)
    assert payroll_row(owner, "2026-10", world.doctor_a)["billed"] == "0.00"
    assert payroll_row(owner, "2026-11", world.doctor_a)["billed"] == "700.00"


def test_doctor_without_terms_accrues_nothing(world):
    procedure(world, amount="700")
    row = payroll_row(owner_of(world), "2026-10", world.doctor_a)
    assert (row["compensation"], row["billed"], row["accrued"]) == (None, "700.00", "0.00")


def test_payroll_is_owner_only_and_per_branch(world):
    assert world.client(world.admin_a).get("/api/v1/payroll/?month=2026-10").status_code == 403
    assert world.client(world.doctor_a).get("/api/v1/payroll/?month=2026-10").status_code == 403
    assert terms(world).status_code == 201
    assert (
        world.client(world.admin_a)
        .post(
            "/api/v1/compensations/",
            {"doctor": str(world.doctor_a.pk), "percent": "99", "effective_from": "2026-10"},
            format="json",
        )
        .status_code
        == 403
    )
    # A doctor of another branch is not a valid choice here.
    assert (
        terms(
            world, doctor=Membership.objects.create(user=world.doctor_a2.user, clinic=world.branch_b, role="doctor")
        ).status_code
        == 400
    )

    owner_all = world.client(world.owner, organization=world.org)
    rows = owner_all.get("/api/v1/payroll/?month=2026-10").json()["rows"]
    assert {row["clinic_name"] for row in rows} == {"Branch A", "Branch B"}
    assert owner_all.post("/api/v1/payroll/pay/", {}, format="json").json()["errors"] == {"clinic": "clinic_required"}
    assert owner_of(world).get("/api/v1/payroll/?month=10-2026").status_code == 400


def test_compensation_history_is_append_only(world):
    first = terms(world, percent="20").json()
    terms(world, percent="25", month="2026-11")
    owner = owner_of(world)
    history = owner.get(f"/api/v1/compensations/?doctor={world.doctor_a.pk}").json()["results"]
    assert [row["percent"] for row in history] == ["25.00", "20.00"]
    assert owner.patch(f"/api/v1/compensations/{first['id']}/", {"percent": "1"}, format="json").status_code in {
        403,
        405,
    }
    assert terms(world, percent="101").status_code == 400


# --- Finance report -------------------------------------------------------------


def test_finance_report_totals(world):
    procedure(world, amount="1000", at="2026-10-10T07:00:00Z")
    procedure(world, doctor=world.doctor_a2, patient=world.patient_a2, amount="500", at="2026-10-12T07:00:00Z")
    payment(world, amount="600", at="2026-10-11T07:00:00Z", method="card")
    payment(world, patient=world.patient_a2, amount="500", at="2026-10-12T08:00:00Z")
    procedure(world, amount="300", at="2026-09-10T07:00:00Z")
    expense(world.client(world.admin_a), amount="200", spent_on="2026-10-05")
    expense(owner_of(world), category="staff_salary", amount="100", spent_on="2026-10-06")

    owner = owner_of(world).get("/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31").json()
    assert owner["totals"] == {
        "billed": "1500.00",
        "collected": "1100.00",
        "expenses": "300.00",
        "profit": "800.00",
        "outstanding_debt": "700.00",
        "debtors_count": 1,
    }
    assert owner["previous_totals"]["billed"] == "300.00"
    assert owner["includes_payroll"] is True
    assert owner["payment_methods"][0] == {"method": "card", "amount": "600.00"}
    doctors = {row["doctor"]: (row["billed"], row["collected"]) for row in owner["doctors"]}
    # FIFO: Patient A's 600 pays September's 300 first, then 300 of October's
    # work; both are collected in October for the same doctor.
    assert doctors == {str(world.doctor_a.pk): ("1000.00", "600.00"), str(world.doctor_a2.pk): ("500.00", "500.00")}
    assert sum(Decimal(point["billed"]) for point in owner["series"]) == Decimal("1500")

    admin = world.client(world.admin_a).get("/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31").json()
    assert (admin["totals"]["expenses"], admin["totals"]["profit"], admin["includes_payroll"]) == (
        "200.00",
        None,
        False,
    )


def test_finance_report_access(world):
    assert world.client(world.doctor_a).get("/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31").status_code == 403
    procedure(world, patient=world.patient_b, doctor=world.admin_b, amount="900")
    admin_a = world.client(world.admin_a).get("/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31").json()
    assert admin_a["totals"]["billed"] == "0.00"
    owner_all = world.client(world.owner, organization=world.org)
    combined = owner_all.get("/api/v1/reports/finance/?from=2026-10-01&to=2026-10-31").json()
    assert combined["totals"]["billed"] == "900.00"
