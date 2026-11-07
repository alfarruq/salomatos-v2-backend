import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.patients.models import Patient
from apps.tenancy.models import Clinic, Membership, Organization

PASSWORD = "Str0ng-pass-for-tests"


def make_user(username: str) -> User:
    return User.objects.create_user(username=username, password=PASSWORD, full_name=username.title())


class World:
    """Two organizations; the first has two branches. Every role is represented."""

    def __init__(self):
        self.owner = make_user("owner")
        self.org = Organization.objects.create(name="Smile Group")
        self.org.owners.add(self.owner)
        self.branch_a = Clinic.objects.create(organization=self.org, name="Branch A")
        self.branch_b = Clinic.objects.create(organization=self.org, name="Branch B")

        self.admin_a = self._member("admin_a", self.branch_a, Membership.Role.ADMIN)
        self.doctor_a = self._member("doctor_a", self.branch_a, Membership.Role.DOCTOR)
        self.doctor_a2 = self._member("doctor_a2", self.branch_a, Membership.Role.DOCTOR)
        self.admin_b = self._member("admin_b", self.branch_b, Membership.Role.ADMIN)

        self.other_org = Organization.objects.create(name="Other")
        self.other_clinic = Clinic.objects.create(organization=self.other_org, name="Other clinic")
        self.other_admin = self._member("other_admin", self.other_clinic, Membership.Role.ADMIN)

        self.patient_a = Patient.objects.create(
            clinic=self.branch_a, full_name="Patient A", phone_number="+998900000001", primary_doctor=self.doctor_a
        )
        self.patient_a2 = Patient.objects.create(
            clinic=self.branch_a, full_name="Patient A2", phone_number="+998900000002", primary_doctor=self.doctor_a2
        )
        self.patient_b = Patient.objects.create(
            clinic=self.branch_b, full_name="Patient B", phone_number="+998900000003"
        )
        self.patient_other = Patient.objects.create(
            clinic=self.other_clinic, full_name="Patient Other", phone_number="+998900000004"
        )

    @staticmethod
    def _member(username, clinic, role) -> Membership:
        return Membership.objects.create(user=make_user(username), clinic=clinic, role=role)

    def client(self, user: User | Membership, clinic: Clinic | None = None, organization: Organization | None = None):
        if isinstance(user, Membership):
            clinic = clinic or user.clinic
            user = user.user
        api = APIClient()
        api.force_authenticate(user)
        if clinic is not None:
            api.credentials(HTTP_X_CLINIC_ID=str(clinic.pk))
        if organization is not None:
            api.credentials(HTTP_X_ORGANIZATION_ID=str(organization.pk))
        return api


@pytest.fixture
def world(db) -> World:
    return World()


def ids(response) -> set[str]:
    body = response.json()
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    return {row["id"] for row in rows}


@pytest.fixture(autouse=True)
def fast_password_hashing(settings):
    # Every patient and doctor now gets a hashed bot password; the production
    # hasher's work factor would make the suite crawl without proving anything.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
