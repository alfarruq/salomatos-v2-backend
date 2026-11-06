from apps.tenancy.models import Membership

from .conftest import PASSWORD


def test_doctor_cannot_manage_staff(world):
    client = world.client(world.doctor_a)
    response = client.post(
        "/api/v1/staff/",
        {"username": "new", "full_name": "New", "password": PASSWORD, "role": "admin"},
        format="json",
    )
    assert response.status_code == 403


def test_admin_cannot_grant_owner_role(world):
    client = world.client(world.admin_a)
    response = client.post(
        "/api/v1/staff/",
        {"username": "boss", "full_name": "Boss", "password": PASSWORD, "role": "owner"},
        format="json",
    )
    assert response.status_code == 400


def test_admin_creates_doctor(world):
    client = world.client(world.admin_a)
    response = client.post(
        "/api/v1/staff/",
        {"username": "dr_new", "full_name": "Dr New", "password": PASSWORD, "role": "doctor"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert Membership.objects.get(user__username="dr_new").clinic == world.branch_a
    assert "password" not in response.json()


def test_staff_is_deactivated_not_deleted(world):
    client = world.client(world.admin_a)
    assert client.delete(f"/api/v1/staff/{world.doctor_a2.pk}/").status_code == 204
    world.doctor_a2.refresh_from_db()
    assert world.doctor_a2.is_active is False


def test_admin_cannot_change_owner(world):
    owner_membership = Membership.objects.get(user=world.owner, clinic=world.branch_a)
    client = world.client(world.admin_a)
    assert client.delete(f"/api/v1/staff/{owner_membership.pk}/").status_code == 403


def test_doctor_cannot_edit_clinic(world):
    client = world.client(world.doctor_a)
    assert client.patch("/api/v1/clinic/", {"name": "Hacked"}, format="json").status_code == 403


def test_owner_edits_clinic(world):
    client = world.client(world.owner, clinic=world.branch_a)
    assert client.patch("/api/v1/clinic/", {"name": "Branch A+"}, format="json").status_code == 200


def test_audit_log_is_owner_only(world):
    assert world.client(world.admin_a).get("/api/v1/audit-logs/").status_code == 403
    assert world.client(world.owner, clinic=world.branch_a).get("/api/v1/audit-logs/").status_code == 200
