"""Role -> permission map. The backend owns it; the frontend reads it from /me/.

Permission strings are `<resource>:<action>`. `*:view_all` means "every row of
the clinic"; without it a doctor sees only rows assigned to them.
"""

from rest_framework.permissions import BasePermission

from apps.saas.tokens import is_platform_token
from apps.tenancy.models import Membership

Role = Membership.Role

_DOCTOR = {
    "clinic:view",
    "staff:view",
    "patient:view",
    "patient:manage",
    "appointment:view",
    "appointment:manage",
    "service:view",
    "prescription:view",
    "prescription:manage",
    "attachment:view",
    "attachment:manage",
    "chart:view",
    "chart:manage",
    "plan:view",
    "plan:manage",
    "procedure:view",
    "procedure:manage",
    "payment:view",
    # The Moliya section's cross-patient lists (payments journal, debtors); the owner's, and a doctor's own patients.
    "finance:view",
    # Prices and paid amounts on procedures, plans and the price list.
    "money:view",
    # A patient's outstanding debt: stays visible even when money is hidden from a doctor.
    "patient:debt",
    # Read back a patient's bot login; a doctor only for patients they can see.
    "patient:bot_access",
    # A doctor's own figures only; views narrow to the caller without `*:view_all`.
    "statistics:view",
    "payroll:view_own",
    # Dictate a form draft; the form's own `*:manage` permission is checked too.
    "voice:use",
}

# Money an admin can be given, by how much the owner allows. None of it is in the
# base role: `permissions_for` adds the tier that applies.
_ADMIN_DEBTS = {"patient:debt"}
_ADMIN_FULL = _ADMIN_DEBTS | {"money:view", "payment:view", "payment:manage"}

# The front desk of one branch. Staff, the price list, the clinic profile and the
# whole Moliya section (reports, expenses, the payments journal) are the owner's
# ("Boshqaruv"), and so are statistics.
_ADMIN = (_DOCTOR - {"statistics:view", "payroll:view_own", "finance:view"} - _ADMIN_FULL) | {
    "patient:view_all",
    "patient:archive",
    "appointment:view_all",
    "chair:manage",
    "procedure:void",
}

_OWNER = (
    _ADMIN
    | _ADMIN_FULL
    | {
        "finance:view",
        "report:view",
        "expense:view",
        "expense:manage",
        # Open, rename and close branches; also checked against Organization.owners.
        "branch:manage",
        "clinic:manage",
        "staff:manage",
        "service:manage",
        "specialty:manage",
        "statistics:view",
        "statistics:view_all",
        "staff:manage_owners",
        "audit:view",
        "payment:void",
        "expense:void",
        "payroll:view",
        "payroll:manage",
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.OWNER: frozenset(_OWNER),
    Role.ADMIN: frozenset(_ADMIN),
    Role.DOCTOR: frozenset(_DOCTOR),
}


# What the owner can hide from doctors: prices, the payments ("Moliya") and the doctor's own pay.
MONEY_PERMISSIONS = frozenset({"money:view", "payment:view", "finance:view", "payroll:view_own"})


def doctor_sees_money(membership: Membership) -> bool:
    if not membership.can_see_money:
        return False
    return membership.clinic_id is None or membership.clinic.doctors_see_money


def admin_money_tier(membership: Membership) -> frozenset[str]:
    """What money an admin gets: nothing, only debts, or everything but the Moliya section.

    The clinic switch overrides the admin's own; with both on, `debts_only` narrows to debts.
    """
    clinic_allows = membership.clinic_id is None or membership.clinic.admins_see_money
    if not clinic_allows or not membership.can_see_money:
        return frozenset()
    return frozenset(_ADMIN_DEBTS if membership.debts_only else _ADMIN_FULL)


def permissions_for(membership: Membership | None) -> frozenset[str]:
    if membership is None or not membership.is_active:
        return frozenset()
    granted = ROLE_PERMISSIONS.get(membership.role, frozenset())
    if membership.role == Role.DOCTOR and not doctor_sees_money(membership):
        granted = granted - MONEY_PERMISSIONS
    elif membership.role == Role.ADMIN:
        granted = granted | admin_money_tier(membership)
    return granted


def can_see_money(request) -> bool:
    return "money:view" in permissions_for(getattr(request, "membership", None))


class HasClinicPermission(BasePermission):
    """Checks `view.required_permissions[action]` against the request's membership.

    Views list a permission for every action they expose; an action missing
    from the map is denied, so a new endpoint is closed until someone opens it.
    """

    def has_permission(self, request, view):
        # A platform token never opens clinic data, even if its user were given a membership.
        if is_platform_token(request.auth):
            return False
        required = getattr(view, "required_permissions", {}).get(
            getattr(view, "action", None) or request.method.lower()
        )
        if required is None:
            return False
        granted = permissions_for(getattr(request, "membership", None))
        return required in granted
