from django.core.management import call_command

from apps.audit.models import AuditLog
from apps.catalog.models import Service, ServiceCategory
from apps.tenancy.models import Clinic, Membership, Organization, Specialty
from apps.tenancy.services import create_organization, ensure_default_branch

from .conftest import ids, make_user


def test_new_organization_gets_a_default_branch(db):
    owner = make_user("solo_owner")
    organization = create_organization("Solo Dental", [owner])
    branch = organization.clinics.get()
    assert branch.name == "Solo Dental"
    assert Membership.objects.filter(user=owner, clinic=branch, role=Membership.Role.OWNER).exists()


def test_default_branch_is_not_added_twice(db):
    organization = Organization.objects.create(name="Twice")
    first = ensure_default_branch(organization)
    assert ensure_default_branch(organization) == first
    assert organization.clinics.count() == 1


def test_create_organization_command(db):
    make_user("cmd_owner")
    call_command("create_organization", "Cmd Dental", owner=["cmd_owner"])
    assert Clinic.objects.filter(organization__name="Cmd Dental").count() == 1


def test_owner_lists_branches_of_own_organization_only(world):
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.get("/api/v1/branches/")
    assert response.status_code == 200
    assert ids(response) == {str(world.branch_a.pk), str(world.branch_b.pk)}


def test_owner_lists_branches_in_all_branches_mode(world):
    response = world.client(world.owner, organization=world.org).get("/api/v1/branches/")
    assert ids(response) == {str(world.branch_a.pk), str(world.branch_b.pk)}


def test_admin_and_doctor_cannot_see_branches(world):
    for member in (world.admin_a, world.doctor_a):
        assert world.client(member).get("/api/v1/branches/").status_code == 403


def test_owner_role_in_one_branch_is_not_organization_ownership(world):
    # The owner role can be granted inside one clinic; that person does not own the other branches.
    local_owner = Membership.objects.create(
        user=make_user("local_owner"), clinic=world.branch_a, role=Membership.Role.OWNER
    )
    client = world.client(local_owner)
    assert client.get("/api/v1/branches/").status_code == 404
    assert client.post("/api/v1/branches/", {"name": "Sneaky"}, format="json").status_code == 404


def test_owner_opens_a_branch_and_holds_it(world):
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.post("/api/v1/branches/", {"name": "Branch C", "address": "Main st"}, format="json")
    assert response.status_code == 201, response.json()
    branch = Clinic.objects.get(pk=response.json()["id"])
    assert branch.organization == world.org
    assert Membership.objects.filter(user=world.owner, clinic=branch, role=Membership.Role.OWNER).exists()
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, target_id=branch.pk).exists()
    # Nobody else of branch A is given the new branch.
    assert not Membership.objects.filter(clinic=branch).exclude(user=world.owner).exists()


def test_branch_name_is_unique_within_organization(world):
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.post("/api/v1/branches/", {"name": "branch b"}, format="json")
    assert response.status_code == 400
    assert "name" in response.json()["errors"]


def test_new_branch_can_copy_price_list(world):
    specialty = Specialty.objects.create(clinic=world.branch_a, name="Surgeon")
    category = ServiceCategory.objects.create(clinic=world.branch_a, name="Surgery")
    Service.objects.create(
        clinic=world.branch_a, name="Extraction", price=200000, category=category, specialty=specialty
    )
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.post(
        "/api/v1/branches/", {"name": "Branch C", "copy_catalog_from": str(world.branch_a.pk)}, format="json"
    )
    assert response.status_code == 201, response.json()
    copied = Service.objects.get(clinic_id=response.json()["id"])
    assert copied.name == "Extraction" and copied.price == 200000
    assert copied.category.clinic_id == copied.clinic_id
    assert copied.specialty.clinic_id == copied.clinic_id


def test_price_list_cannot_be_copied_from_another_organization(world):
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.post(
        "/api/v1/branches/", {"name": "Branch C", "copy_catalog_from": str(world.other_clinic.pk)}, format="json"
    )
    assert response.status_code == 400
    assert "copy_catalog_from" in response.json()["errors"]


def test_foreign_branch_cannot_be_edited(world):
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.patch(f"/api/v1/branches/{world.other_clinic.pk}/", {"name": "Mine"}, format="json")
    assert response.status_code == 404


def test_owner_renames_a_branch(world):
    client = world.client(world.owner, clinic=world.branch_a)
    response = client.patch(f"/api/v1/branches/{world.branch_b.pk}/", {"name": "Yunusobod"}, format="json")
    assert response.status_code == 200
    world.branch_b.refresh_from_db()
    assert world.branch_b.name == "Yunusobod"


def test_closed_branch_drops_out_and_can_reopen(world):
    client = world.client(world.owner, clinic=world.branch_a)
    assert client.delete(f"/api/v1/branches/{world.branch_b.pk}/").status_code == 204
    # Its staff can no longer open it.
    assert world.client(world.admin_b).get("/api/v1/patients/").status_code == 404
    reopened = client.post(f"/api/v1/branches/{world.branch_b.pk}/reactivate/")
    assert reopened.status_code == 200
    assert reopened.json()["is_active"] is True


def test_last_open_branch_cannot_be_closed(world):
    client = world.client(world.owner, clinic=world.branch_a)
    assert client.delete(f"/api/v1/branches/{world.branch_b.pk}/").status_code == 204
    response = client.delete(f"/api/v1/branches/{world.branch_a.pk}/")
    assert response.status_code == 400


def test_writes_need_one_branch(world):
    response = world.client(world.owner, organization=world.org).post(
        "/api/v1/branches/", {"name": "Branch C"}, format="json"
    )
    assert response.status_code == 400


def test_staff_is_created_in_the_branch_of_the_header(world):
    client = world.client(world.owner, clinic=world.branch_b)
    response = client.post(
        "/api/v1/staff/",
        {"username": "dr_b", "full_name": "Dr B", "password": "Str0ng-pass-for-tests", "role": "doctor"},
        format="json",
    )
    assert response.status_code == 201
    doctor = Membership.objects.get(user__username="dr_b")
    assert doctor.clinic == world.branch_b
    # Branch A's front desk does not get branch B's doctor in its pickers.
    assert str(doctor.pk) not in ids(world.client(world.admin_a).get("/api/v1/staff/"))


def test_branch_counts(world):
    response = world.client(world.owner, clinic=world.branch_a).get("/api/v1/branches/")
    rows = {row["id"]: row for row in response.json()}
    assert rows[str(world.branch_a.pk)]["staff_count"] == 3
    assert rows[str(world.branch_a.pk)]["patient_count"] == 2
