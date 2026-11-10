from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.saas.models import Contract, PlatformEvent, PlatformPayment
from apps.saas.tokens import platform_refresh_for
from apps.tenancy.models import Clinic, Membership
from tests.conftest import PASSWORD, make_user

BASE = "/api/platform/v1"


@pytest.fixture
def operator(db):
    user = make_user("vendor")
    user.is_platform_operator = True
    user.save()
    return user


def platform_client(user) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {platform_refresh_for(user).access_token}")
    return api


@pytest.fixture
def platform(operator) -> APIClient:
    return platform_client(operator)


def new_customer(platform, **extra):
    body = {
        "name": "Tabassum",
        "contract": {"install_fee": "1000.00", "server_fee_yearly": "80.00"},
        "clinic": {"name": "Tabassum Chilonzor", "phone_number": "+998901112233"},
        "owner": {"username": "tabassum_owner", "full_name": "Owner"},
        **extra,
    }
    response = platform.post(f"{BASE}/organizations/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


# --- Who may use the platform side ---------------------------------------------


def test_platform_login_only_for_operators(world, operator):
    api = APIClient()
    ok = api.post(f"{BASE}/auth/login/", {"username": "vendor", "password": PASSWORD}, format="json")
    assert ok.status_code == 200
    staff = api.post(f"{BASE}/auth/login/", {"username": "owner", "password": PASSWORD}, format="json")
    assert staff.status_code == 400
    # The clinic login refuses an operator, with the same answer as a wrong password.
    clinic = api.post("/api/v1/auth/login/", {"username": "vendor", "password": PASSWORD}, format="json")
    assert clinic.status_code == 400


def test_platform_refresh_keeps_scope_and_clinic_refresh_refuses_it(operator):
    api = APIClient()
    tokens = api.post(f"{BASE}/auth/login/", {"username": "vendor", "password": PASSWORD}, format="json").json()
    refresh = tokens["result"]["refresh_token"]
    assert api.post("/api/v1/auth/refresh/", {"refresh_token": refresh}, format="json").status_code == 401
    tokens = api.post(f"{BASE}/auth/login/", {"username": "vendor", "password": PASSWORD}, format="json").json()
    renewed = api.post(f"{BASE}/auth/refresh/", {"refresh_token": tokens["result"]["refresh_token"]}, format="json")
    assert renewed.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {renewed.json()['result']['access_token']}")
    assert api.get(f"{BASE}/auth/me/").status_code == 200


def test_clinic_token_cannot_reach_platform(world):
    for member in (world.owner, world.admin_a):
        api = world.client(member if not isinstance(member, Membership) else member)
        assert api.get(f"{BASE}/organizations/").status_code == 403
    # Even a flagged operator needs a platform token, not a clinic one.
    api = APIClient()
    world.owner.is_platform_operator = True
    world.owner.save()
    api.force_authenticate(world.owner)
    assert api.get(f"{BASE}/organizations/").status_code == 403


def test_platform_token_cannot_reach_clinic_data(world, operator):
    # Give the operator a membership by hand: the token scope still keeps clinic data closed.
    Membership.objects.create(user=operator, clinic=world.branch_a, role=Membership.Role.OWNER)
    api = platform_client(operator)
    api.credentials(HTTP_AUTHORIZATION=api._credentials["HTTP_AUTHORIZATION"], HTTP_X_CLINIC_ID=str(world.branch_a.pk))
    assert api.get("/api/v1/patients/").status_code == 403


def test_anonymous_is_refused(db):
    assert APIClient().get(f"{BASE}/organizations/").status_code == 401


# --- Customers ------------------------------------------------------------------


def test_create_customer_with_branch_and_owner(platform):
    body = new_customer(platform)
    organization = body["organization"]
    assert organization["contract"]["install_fee"] == "1000.00"
    assert [c["name"] for c in organization["clinics"]] == ["Tabassum Chilonzor"]
    assert organization["owners"][0]["username"] == "tabassum_owner"
    assert organization["billing"]["install_due"] == "1000.00"
    assert organization["billing"]["server_overdue"] is True

    # The owner signs in to the clinic app with the temporary password.
    login = APIClient().post(
        "/api/v1/auth/login/",
        {"username": body["owner_username"], "password": body["owner_temporary_password"]},
        format="json",
    )
    assert login.status_code == 200
    clinic = Clinic.objects.get(name="Tabassum Chilonzor")
    assert Membership.objects.filter(clinic=clinic, role=Membership.Role.OWNER).count() == 1
    assert PlatformEvent.objects.filter(action=PlatformEvent.Action.CREATE).exists()


def test_create_refuses_taken_username(platform, world):
    response = platform.post(
        f"{BASE}/organizations/",
        {"name": "X", "clinic": {"name": "X"}, "owner": {"username": "owner", "full_name": "X"}},
        format="json",
    )
    assert response.status_code == 400


def test_add_branch_gives_every_owner_access(platform):
    organization = new_customer(platform)["organization"]
    response = platform.post(f"{BASE}/organizations/{organization['id']}/clinics/", {"name": "Second"}, format="json")
    assert response.status_code == 201
    second = Clinic.objects.get(name="Second")
    assert Membership.objects.filter(clinic=second, role=Membership.Role.OWNER).count() == 1


def test_update_contract(platform):
    organization = new_customer(platform)["organization"]
    response = platform.patch(
        f"{BASE}/organizations/{organization['id']}/",
        {"name": "Tabassum Group", "contract": {"voice_enabled": True, "voice_monthly_limit": 500}},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Tabassum Group"
    contract = Contract.objects.get(organization_id=organization["id"])
    assert contract.voice_enabled is True
    assert contract.voice_monthly_limit == 500
    assert contract.install_fee == 1000


def test_no_delete_route(platform, world):
    assert platform.delete(f"{BASE}/organizations/{world.org.pk}/").status_code == 405


def test_suspend_blocks_every_branch_and_reactivate_restores(platform, world):
    api = world.client(world.admin_a)
    assert api.get("/api/v1/patients/").status_code == 200
    assert platform.post(f"{BASE}/organizations/{world.org.pk}/suspend/").status_code == 200
    assert api.get("/api/v1/patients/").status_code == 404
    assert world.client(world.admin_b).get("/api/v1/patients/").status_code == 404
    assert world.client(world.admin_a).get("/api/v1/auth/me/").json()["memberships"] == []
    # Another customer is untouched.
    assert world.client(world.other_admin).get("/api/v1/patients/").status_code == 200
    assert platform.post(f"{BASE}/organizations/{world.org.pk}/reactivate/").status_code == 200
    assert api.get("/api/v1/patients/").status_code == 200


def test_suspend_one_branch(platform, world):
    assert platform.post(f"{BASE}/clinics/{world.branch_a.pk}/suspend/").status_code == 200
    assert world.client(world.admin_a).get("/api/v1/patients/").status_code == 404
    assert world.client(world.admin_b).get("/api/v1/patients/").status_code == 200


def test_reset_owner_password(platform, world):
    response = platform.post(
        f"{BASE}/organizations/{world.org.pk}/reset-owner-password/", {"owner": str(world.owner.pk)}, format="json"
    )
    assert response.status_code == 200
    password = response.json()["temporary_password"]
    world.owner.refresh_from_db()
    assert world.owner.check_password(password)
    # Someone who is not an owner of this customer cannot be reset through it.
    other = platform.post(
        f"{BASE}/organizations/{world.org.pk}/reset-owner-password/",
        {"owner": str(world.other_admin.user.pk)},
        format="json",
    )
    assert other.status_code == 400


def test_usage_is_counts_only(platform, world):
    response = platform.get(f"{BASE}/organizations/{world.org.pk}/usage/")
    assert response.status_code == 200
    body = response.json()
    assert body["patients"] == 3
    assert body["clinics"] == 2
    text = response.content.decode()
    for patient in (world.patient_a, world.patient_b):
        assert patient.full_name not in text
        assert patient.phone_number not in text


def test_detail_has_no_patient_data(platform, world):
    text = platform.get(f"{BASE}/organizations/{world.org.pk}/").content.decode()
    assert "Patient A" not in text
    assert "+998900000001" not in text


# --- Money ----------------------------------------------------------------------


def pay(platform, organization_id, **fields):
    body = {"organization": str(organization_id), "amount": "80.00", "paid_on": str(date.today()), **fields}
    return platform.post(f"{BASE}/payments/", body, format="json")


def test_server_payment_extends_paid_until_and_void_rolls_back(platform, world):
    Contract.objects.create(organization=world.org, server_fee_yearly=80)
    until = date.today() + timedelta(days=365)
    first = pay(platform, world.org.pk, kind="server", covers_until=str(until))
    assert first.status_code == 201, first.json()
    detail = platform.get(f"{BASE}/organizations/{world.org.pk}/").json()
    assert detail["billing"]["server_paid_until"] == str(until)
    assert detail["billing"]["server_overdue"] is False

    voided = platform.post(f"{BASE}/payments/{first.json()['id']}/void/", {"reason": "typo"}, format="json")
    assert voided.status_code == 200
    detail = platform.get(f"{BASE}/organizations/{world.org.pk}/").json()
    assert detail["billing"]["server_paid_until"] is None
    assert detail["billing"]["server_overdue"] is True
    again = platform.post(f"{BASE}/payments/{first.json()['id']}/void/", {"reason": "x"}, format="json")
    assert again.status_code == 400


def test_payment_rules_per_kind(platform, world):
    assert pay(platform, world.org.pk, kind="server").status_code == 400
    assert pay(platform, world.org.pk, kind="sms").status_code == 400
    sms = pay(platform, world.org.pk, kind="sms", sms_credits=1000, amount="20.00")
    assert sms.status_code == 201
    assert sms.json()["currency"] == "USD"
    assert sms.json()["covers_until"] is None
    install = pay(platform, world.org.pk, kind="install", amount="400.00", currency="UZS")
    assert install.json()["currency"] == "UZS"
    detail = platform.get(f"{BASE}/organizations/{world.org.pk}/").json()
    assert detail["billing"]["sms_credits"] == 1000


def test_payments_are_never_edited_or_deleted(platform, world):
    payment = pay(platform, world.org.pk, kind="other").json()
    assert platform.patch(f"{BASE}/payments/{payment['id']}/", {"amount": "1"}, format="json").status_code == 405
    assert platform.delete(f"{BASE}/payments/{payment['id']}/").status_code == 405


def test_payment_list_filters(platform, world):
    pay(platform, world.org.pk, kind="other")
    pay(platform, world.other_org.pk, kind="other")
    response = platform.get(f"{BASE}/payments/", {"organization": str(world.org.pk)})
    assert [row["organization"] for row in response.json()["results"]] == [str(world.org.pk)]
    assert platform.get(f"{BASE}/payments/", {"organization": "nope"}).status_code == 400


def test_voice_payment_turns_the_add_on_on(platform, world, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    api = world.client(world.doctor_a)
    assert api.get("/api/v1/voice/status/").json()["subscribed"] is False
    platform.patch(f"{BASE}/organizations/{world.org.pk}/", {"contract": {"voice_enabled": True}}, format="json")
    pay(platform, world.org.pk, kind="voice", amount="10.00", covers_until=str(date.today() + timedelta(days=30)))
    status = api.get("/api/v1/voice/status/").json()
    assert status["subscribed"] is True
    assert status["enabled"] is True


def test_dashboard(platform, world):
    Contract.objects.create(organization=world.org, install_fee=1000, server_fee_yearly=80)
    pay(platform, world.org.pk, kind="install", amount="300.00")
    response = platform.get(f"{BASE}/dashboard/")
    assert response.status_code == 200
    body = response.json()
    assert body["organizations"] == 2
    assert {"currency": "USD", "kind": "install", "total": "300.00"} in body["collected_this_month"]
    assert [row["name"] for row in body["server_overdue"]] == ["Smile Group"]
    assert body["install_due"][0]["due"] == "700.00"
    assert PlatformPayment.objects.count() == 1


# --- Issued passwords -------------------------------------------------------------


def test_issued_password_is_readable_until_the_owner_changes_it(platform):
    body = new_customer(platform)
    organization_id = body["organization"]["id"]
    temporary = body["owner_temporary_password"]
    detail = platform.get(f"{BASE}/organizations/{organization_id}/").json()
    assert detail["owners"][0]["temporary_password"] == temporary
    assert PlatformEvent.objects.filter(action=PlatformEvent.Action.REVEAL_PASSWORD).exists()
    # The list shows the login but never a password.
    row = platform.get(f"{BASE}/organizations/").json()["results"][0]
    assert row["owner_usernames"] == ["tabassum_owner"]
    assert temporary not in str(row)

    owner = APIClient()
    tokens = owner.post(
        "/api/v1/auth/login/", {"username": "tabassum_owner", "password": temporary}, format="json"
    ).json()
    owner.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['result']['access_token']}")
    changed = owner.post(
        "/api/v1/auth/change-password/",
        {"old_password": temporary, "new_password": "Another-Str0ng-pass"},
        format="json",
    )
    assert changed.status_code == 204
    detail = platform.get(f"{BASE}/organizations/{organization_id}/").json()
    assert detail["owners"][0]["temporary_password"] is None
    assert "Another-Str0ng-pass" not in str(detail)


def test_reset_issues_a_new_readable_password(platform, world):
    reset = platform.post(
        f"{BASE}/organizations/{world.org.pk}/reset-owner-password/", {"owner": str(world.owner.pk)}, format="json"
    ).json()
    detail = platform.get(f"{BASE}/organizations/{world.org.pk}/").json()
    owner = next(row for row in detail["owners"] if row["username"] == "owner")
    assert owner["temporary_password"] == reset["temporary_password"]


def test_owners_without_an_issued_password_show_none(platform, world):
    detail = platform.get(f"{BASE}/organizations/{world.org.pk}/").json()
    assert all(row["temporary_password"] is None for row in detail["owners"])


def test_credentials_sheet_lists_logins_with_current_passwords(platform, world):
    body = new_customer(platform)
    sheet = platform.get(f"{BASE}/credentials/")
    assert sheet.status_code == 200
    rows = {row["username"]: row for row in sheet.json()}
    assert rows["tabassum_owner"]["temporary_password"] == body["owner_temporary_password"]
    assert rows["owner"]["temporary_password"] is None
    assert PlatformEvent.objects.filter(action=PlatformEvent.Action.REVEAL_PASSWORD).exists()


def test_credentials_sheet_is_platform_only(world):
    assert world.client(world.owner).get(f"{BASE}/credentials/").status_code == 403
    assert APIClient().get(f"{BASE}/credentials/").status_code == 401
