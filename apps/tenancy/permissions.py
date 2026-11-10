"""Role -> permission map. The backend owns it; the frontend reads it from /me/.

Permission strings are `<resource>:<action>`. `*:view_all` means "every row of
the clinic"; without it a doctor sees only rows assigned to them.
"""

from rest_framework.permissions import BasePermission

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
    # Read back a patient's bot login; a doctor only for patients they can see.
    "patient:bot_access",
    # A doctor's own figures only; views narrow to the caller without `*:view_all`.
    "statistics:view",
    "payroll:view_own",
    # Dictate a form draft; the form's own `*:manage` permission is checked too.
    "voice:use",
}

# The front desk of one branch. Staff, the price list and the clinic profile are
# the owner's ("Boshqaruv"), and so are statistics.
_ADMIN = (_DOCTOR - {"statistics:view", "payroll:view_own"}) | {
    "patient:view_all",
    "patient:archive",
    "appointment:view_all",
    "chair:manage",
    "procedure:void",
    "payment:manage",
    "report:view",
    "expense:view",
    "expense:manage",
}

_OWNER = _ADMIN | {
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

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.OWNER: frozenset(_OWNER),
    Role.ADMIN: frozenset(_ADMIN),
    Role.DOCTOR: frozenset(_DOCTOR),
}


def permissions_for(membership: Membership | None) -> frozenset[str]:
    if membership is None or not membership.is_active:
        return frozenset()
    return ROLE_PERMISSIONS.get(membership.role, frozenset())


class HasClinicPermission(BasePermission):
    """Checks `view.required_permissions[action]` against the request's membership.

    Views list a permission for every action they expose; an action missing
    from the map is denied, so a new endpoint is closed until someone opens it.
    """

    def has_permission(self, request, view):
        required = getattr(view, "required_permissions", {}).get(
            getattr(view, "action", None) or request.method.lower()
        )
        if required is None:
            return False
        granted = permissions_for(getattr(request, "membership", None))
        return required in granted
