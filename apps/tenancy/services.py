from apps.tenancy.models import Clinic, Membership


def ensure_owner_membership(clinic: Clinic, user) -> None:
    Membership.objects.update_or_create(
        user=user,
        clinic=clinic,
        defaults={"role": Membership.Role.OWNER, "is_active": True},
    )
