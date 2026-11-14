import importlib

from django.apps import apps as django_apps

from apps.catalog.models import Service
from apps.tenancy.branches import copy_catalog
from apps.tenancy.models import Clinic, Membership, Specialty


def dental(clinic):
    return Specialty.objects.get(clinic=clinic, is_dental=True)


def test_every_new_clinic_gets_one_dental_specialty(world):
    for clinic in (world.branch_a, world.branch_b, world.other_clinic):
        assert Specialty.objects.filter(clinic=clinic, is_dental=True).count() == 1
        assert dental(clinic).name == "Stomatolog"


def test_dental_specialty_is_listed_first_and_flagged(world):
    Specialty.objects.create(clinic=world.branch_a, name="Kosmetolog")
    rows = world.client(world.owner, clinic=world.branch_a).get("/api/v1/specialties/").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert [(row["name"], row["is_dental"]) for row in rows] == [("Stomatolog", True), ("Kosmetolog", False)]


def test_owner_cannot_delete_or_rename_the_dental_specialty(world):
    api = world.client(world.owner, clinic=world.branch_a)
    url = f"/api/v1/specialties/{dental(world.branch_a).pk}/"
    assert api.delete(url).status_code == 400
    assert api.patch(url, {"name": "Tish"}, format="json").status_code == 400
    assert dental(world.branch_a).name == "Stomatolog"


def test_a_second_dental_specialty_cannot_be_created(world):
    api = world.client(world.owner, clinic=world.branch_a)
    response = api.post("/api/v1/specialties/", {"name": "Kosmetolog", "is_dental": True}, format="json")
    assert response.status_code == 201
    assert response.json()["is_dental"] is False
    assert api.post("/api/v1/specialties/", {"name": "stomatolog"}, format="json").status_code == 400


def test_other_specialties_can_still_be_deleted(world):
    other = Specialty.objects.create(clinic=world.branch_a, name="Kosmetolog")
    api = world.client(world.owner, clinic=world.branch_a)
    assert api.delete(f"/api/v1/specialties/{other.pk}/").status_code == 204


def test_staff_rows_say_whether_the_doctor_is_a_dentist(world):
    world.doctor_a.specialty = dental(world.branch_a)
    world.doctor_a.save()
    response = world.client(world.owner, clinic=world.branch_a).get(f"/api/v1/staff/{world.doctor_a.pk}/")
    assert response.json()["specialty_is_dental"] is True
    response = world.client(world.owner, clinic=world.branch_a).get(f"/api/v1/staff/{world.doctor_a2.pk}/")
    assert response.json()["specialty_is_dental"] is False


def test_copied_price_list_keeps_dental_services_on_the_new_branch_dental_specialty(world):
    Service.objects.create(clinic=world.branch_a, name="Plomba", price=1, specialty=dental(world.branch_a))
    target = Clinic.objects.create(organization=world.org, name="Branch C")
    copy_catalog(world.branch_a, target)
    assert Service.objects.get(clinic=target).specialty == dental(target)
    assert Specialty.objects.filter(clinic=target).count() == 1


def test_migration_folds_hand_typed_duplicates_into_one(world):
    clinic = world.branch_a
    Specialty.objects.filter(clinic=clinic).delete()
    typo = Specialty.objects.create(clinic=clinic, name="Stamatolog")
    spare = Specialty.objects.create(clinic=clinic, name="Стоматолог")
    Specialty.objects.create(clinic=clinic, name="Ortodont")
    world.doctor_a.specialty = typo
    world.doctor_a.save()
    world.doctor_a2.specialty = spare
    world.doctor_a2.save()
    Service.objects.create(clinic=clinic, name="Plomba", price=1, specialty=typo)

    migration = importlib.import_module("apps.tenancy.migrations.0002_dental_specialty")
    migration.give_every_clinic_one_dental_specialty(django_apps, None)

    kept = Specialty.objects.get(clinic=clinic, is_dental=True)
    assert kept.pk == typo.pk and kept.name == "Stomatolog"
    assert set(Specialty.objects.filter(clinic=clinic).values_list("name", flat=True)) == {"Stomatolog", "Ortodont"}
    assert set(Membership.objects.filter(specialty=kept)) == {world.doctor_a, world.doctor_a2}
    assert Service.objects.get(clinic=clinic, name="Plomba").specialty == kept
