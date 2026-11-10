import uuid

from rest_framework.exceptions import NotFound, ValidationError

from apps.tenancy.models import Membership, Organization

CLINIC_HEADER = "HTTP_X_CLINIC_ID"
ORGANIZATION_HEADER = "HTTP_X_ORGANIZATION_ID"


def _uuid_header(request, header: str, field: str) -> uuid.UUID | None:
    raw = request.META.get(header)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as err:
        raise ValidationError({field: f"{field} id must be a UUID."}, code=f"{field}_invalid") from err


def resolve_membership(request) -> Membership:
    """Reads `X-Clinic-Id` and returns the caller's active membership in that clinic.

    A clinic the user does not belong to answers 404, the same as one that does
    not exist, so ids of other tenants cannot be probed.
    """
    clinic_id = _uuid_header(request, CLINIC_HEADER, "clinic")
    if clinic_id is None:
        raise ValidationError({"clinic": "X-Clinic-Id header is required."}, code="clinic_required")
    membership = (
        Membership.objects.select_related("clinic", "user")
        .filter(
            user=request.user,
            clinic_id=clinic_id,
            is_active=True,
            clinic__is_active=True,
            # A suspended customer (unpaid, offboarded) loses every branch at once.
            clinic__organization__is_active=True,
        )
        .first()
    )
    if membership is None:
        raise NotFound("Clinic not found.")
    return membership


def resolve_organization(request) -> Organization | None:
    """Reads `X-Organization-Id` ("all branches" mode). Only the organization's owners may use it."""
    organization_id = _uuid_header(request, ORGANIZATION_HEADER, "organization")
    if organization_id is None:
        return None
    organization = Organization.objects.filter(pk=organization_id, owners=request.user, is_active=True).first()
    if organization is None:
        raise NotFound("Organization not found.")
    return organization
