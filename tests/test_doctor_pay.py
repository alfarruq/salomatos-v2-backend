"""Pay terms set when a doctor is added, and the doctor's own view of their month."""

from apps.audit.models import AuditLog
from apps.finance.models import Compensation
from apps.tenancy.models import Membership

from .conftest import PASSWORD
from .test_finance import owner_of, payment, payroll_row, procedure, terms

EARNINGS = "/api/v1/me/earnings/?month=2026-10"


def new_doctor(client, **fields):
    body = {"username": "dr_new", "full_name": "Dr New", "password": PASSWORD, "role": "doctor", **fields}
    return client.post("/api/v1/staff/", body, format="json")


# --- Terms on the add-doctor form ----------------------------------------------


def test_owner_adds_a_doctor_with_pay_terms(world):
    response = new_doctor(owner_of(world), compensation={"percent": "50", "fixed": "3000000"})
    assert response.status_code == 201, response.json()
    current = response.json()["current_compensation"]
    assert (current["percent"], current["fixed"], current["base"]) == ("50.00", "3000000.00", "collected")

    member = Membership.objects.get(user__username="dr_new")
    row = Compensation.objects.get(doctor=member)
    assert row.effective_from.day == 1
    assert row.created_by == Membership.objects.get(user=world.owner, clinic=world.branch_a)


def test_the_three_pay_modes(world):
    owner = owner_of(world)
    for username, pay in (("salary", {"fixed": "4000000"}), ("share", {"percent": "40"})):
        response = new_doctor(owner, username=username, compensation=pay)
        assert response.status_code == 201, response.json()
    assert Compensation.objects.get(doctor__user__username="salary").percent == 0
    assert Compensation.objects.get(doctor__user__username="share").fixed == 0

    # Neither a salary nor a share is no agreement at all.
    response = new_doctor(owner, compensation={"percent": "0", "fixed": "0"})
    assert response.status_code == 400
    assert "percent" in response.json()["errors"]["compensation"]


def test_a_doctor_may_be_added_without_terms(world):
    response = new_doctor(owner_of(world))
    assert response.status_code == 201
    assert response.json()["current_compensation"] is None
    assert not Compensation.objects.filter(doctor__user__username="dr_new").exists()


def test_pay_terms_rules(world):
    owner = owner_of(world)
    response = new_doctor(owner, role="admin", compensation={"fixed": "1"})
    assert response.status_code == 400
    assert "compensation" in response.json()["errors"]
    assert new_doctor(owner, compensation={"percent": "101"}).status_code == 400
    assert new_doctor(owner, compensation={"fixed": "-1"}).status_code == 400

    # Terms change through /compensations/ from a month, never by editing the doctor.
    response = owner.patch(f"/api/v1/staff/{world.doctor_a.pk}/", {"compensation": {"fixed": "1"}}, format="json")
    assert response.status_code == 400
    assert not Compensation.objects.filter(doctor=world.doctor_a).exists()


def test_current_terms_are_shown_to_the_owner_only(world):
    terms(world, percent="30")
    owner_rows = {row["id"]: row for row in owner_of(world).get("/api/v1/staff/").json()["results"]}
    assert owner_rows[str(world.doctor_a.pk)]["current_compensation"]["percent"] == "30.00"
    assert owner_rows[str(world.doctor_a2.pk)]["current_compensation"] is None
    assert "current_compensation" not in owner_rows[str(world.admin_a.pk)] or (
        owner_rows[str(world.admin_a.pk)]["current_compensation"] is None
    )

    for member in (world.admin_a, world.doctor_a):
        text = world.client(member).get("/api/v1/staff/").content.decode()
        assert "current_compensation" not in text


# --- Payroll: earned vs waiting --------------------------------------------------


def test_payroll_shows_what_still_waits_on_patients(world):
    terms(world, percent="30")
    procedure(world, amount="1000000")
    payment(world, amount="400000", at="2026-10-11T07:00:00Z")

    row = payroll_row(owner_of(world), "2026-10", world.doctor_a)
    assert (row["accrued"], row["pending"], row["pending_share"]) == ("120000.00", "600000.00", "180000.00")
    totals = owner_of(world).get("/api/v1/payroll/?month=2026-10").json()["totals"]
    assert totals["pending_share"] == "180000.00"


def test_billed_terms_have_nothing_pending(world):
    terms(world, percent="30", base="billed")
    procedure(world, amount="1000000")

    row = payroll_row(owner_of(world), "2026-10", world.doctor_a)
    assert (row["accrued"], row["pending"], row["pending_share"]) == ("300000.00", "1000000.00", "0.00")


# --- The doctor's own month --------------------------------------------------------


def test_a_doctor_sees_their_own_earnings(world):
    terms(world, percent="50")
    filling = procedure(world, amount="1000000", at="2026-10-05T07:00:00Z")
    crown = procedure(world, amount="600000", at="2026-10-06T07:00:00Z")
    procedure(world, doctor=world.doctor_a2, patient=world.patient_a2, amount="999000")
    # Oldest work is paid first: the filling is settled, the crown is half paid.
    payment(world, amount="1300000", at="2026-10-07T07:00:00Z")

    body = world.client(world.doctor_a).get(EARNINGS).json()
    assert body["summary"]["doctor"] == str(world.doctor_a.pk)
    assert (body["summary"]["accrued"], body["summary"]["pending_share"]) == ("650000.00", "150000.00")

    lines = {line["procedure"]: line for line in body["lines"]}
    assert set(lines) == {str(filling.pk), str(crown.pk)}
    assert (lines[str(filling.pk)]["status"], lines[str(filling.pk)]["unpaid"]) == ("completed", "0.00")
    assert (lines[str(crown.pk)]["status"], lines[str(crown.pk)]["paid"]) == ("in_progress", "300000.00")
    assert lines[str(crown.pk)]["patient_name"] == world.patient_a.full_name

    assert AuditLog.objects.filter(target_type="finance.earnings", actor=world.doctor_a.user).exists()


def test_older_unpaid_work_stays_on_the_list(world):
    september = procedure(world, amount="500000", at="2026-09-20T07:00:00Z")
    lines = world.client(world.doctor_a).get(EARNINGS).json()["lines"]
    assert [line["procedure"] for line in lines] == [str(september.pk)]

    payment(world, amount="500000", at="2026-09-25T07:00:00Z")
    assert world.client(world.doctor_a).get(EARNINGS).json()["lines"] == []


def test_earnings_without_terms_are_zero(world):
    procedure(world, amount="1000000")
    body = world.client(world.doctor_a).get(EARNINGS).json()
    assert body["summary"]["compensation"] is None
    assert body["summary"]["accrued"] == "0.00"
    assert len(body["lines"]) == 1


def test_earnings_are_the_doctors_alone(world):
    # The owner and the front desk read pay through payroll, not as a doctor.
    for member in (world.admin_a,):
        assert world.client(member).get(EARNINGS).status_code == 403
    assert world.client(world.owner, clinic=world.branch_a).get(EARNINGS).status_code == 403
    # A doctor cannot read another tenant's month by switching the header.
    assert world.client(world.doctor_a, clinic=world.other_clinic).get(EARNINGS).status_code == 404
    # No parameter picks a colleague.
    mine = world.client(world.doctor_a).get(f"{EARNINGS}&doctor={world.doctor_a2.pk}").json()
    assert mine["summary"]["doctor"] == str(world.doctor_a.pk)
    assert world.client(world.doctor_a).get("/api/v1/me/earnings/?month=10-2026").status_code == 400
