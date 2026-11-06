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
}

_ADMIN = _DOCTOR | {
    "staff:manage",
    "patient:view_all",
    "patient:archive",
    "appointment:view_all",
    "service:manage",
    "chair:manage",
    "specialty:manage",
    "procedure:void",
    "payment:manage",
    "report:view",
}

_OWNER = _ADMIN | {
    "clinic:manage",
    "staff:manage_owners",
    "audit:view",
    "payment:void",
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
