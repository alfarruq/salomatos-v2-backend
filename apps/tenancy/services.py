from django.db import transaction

from apps.tenancy.models import Clinic, Membership, Organization


def ensure_owner_membership(clinic: Clinic, user) -> None:
    Membership.objects.update_or_create(
        user=user,
        clinic=clinic,
        defaults={"role": Membership.Role.OWNER, "is_active": True},
    )


def ensure_default_branch(organization: Organization) -> Clinic:
    """Every organization has at least one branch, so a single-branch clinic never sees the concept.

    The first branch takes the organization's name: with one branch the two are
    the same clinic, and that name is what prescriptions and the bot print.
    """
    with transaction.atomic():
        # Locks the organization so two concurrent saves cannot each add a "first" branch.
        Organization.objects.select_for_update().filter(pk=organization.pk).first()
        existing = organization.clinics.order_by("created_at").first()
        if existing is not None:
            return existing
        return Clinic.objects.create(organization=organization, name=organization.name)


def create_organization(name: str, owners=()) -> Organization:
    with transaction.atomic():
        organization = Organization.objects.create(name=name)
        if owners:
            organization.owners.add(*owners)
        ensure_default_branch(organization)
    return organization
