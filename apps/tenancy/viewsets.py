from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenancy.context import resolve_membership, resolve_organization
from apps.tenancy.models import Membership
from apps.tenancy.permissions import HasClinicPermission, permissions_for


class ClinicScopedMixin:
    """Must come first in a view's bases so its hooks win over DRF's mixins.

    Base for every endpoint that reads or writes tenant data.

    - The tenant comes from the `X-Clinic-Id` header and the caller's membership,
      never from the request body or the user row.
    - `get_queryset` is always filtered by that clinic; subclasses narrow it
      further in `scope_queryset`, they never widen it.
    - Writes are stamped with the clinic server-side.
    - Reads and writes of models with `audit_reads`/`audit_writes` are logged.

    "All branches" mode: an organization owner may send `X-Organization-Id`
    instead of `X-Clinic-Id` for the read-only actions a view lists in
    `organization_actions`. Rows of every branch are returned, each with its
    `clinic`. Writes always need one branch, so the new row has a tenant.
    """

    permission_classes = [IsAuthenticated, HasClinicPermission]
    required_permissions: dict[str, str] = {}
    organization_actions: frozenset[str] = frozenset()
    audit_reads = True
    audit_writes = True

    def check_permissions(self, request):
        if request.user and request.user.is_authenticated and not hasattr(request, "membership"):
            self._resolve_scope(request)
        super().check_permissions(request)

    def _resolve_scope(self, request):
        organization = resolve_organization(request)
        if organization is None:
            membership = resolve_membership(request)
            request.membership = membership
            request.clinic = membership.clinic
            request.organization = None
            request.clinic_ids = [membership.clinic_id]
            return
        if (getattr(self, "action", None) or request.method.lower()) not in self.organization_actions:
            raise ValidationError({"clinic": "Choose a branch: this action needs X-Clinic-Id."}, code="clinic_required")
        request.organization = organization
        request.clinic = None
        request.clinic_ids = list(organization.clinics.filter(is_active=True).values_list("id", flat=True))
        # Owners hold the owner role in every branch; an unsaved membership
        # carries that role for the permission check only.
        request.membership = Membership(user=request.user, role=Membership.Role.OWNER, is_active=True)

    def has_perm(self, permission: str) -> bool:
        return permission in permissions_for(self.request.membership)

    def get_queryset(self):
        return self.scope_queryset(super().get_queryset().filter(clinic_id__in=self.request.clinic_ids))

    def scope_queryset(self, queryset):
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save(clinic=self.request.clinic)
        if self.audit_writes:
            record(self.request, AuditLog.Action.CREATE, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        if self.audit_writes:
            record(self.request, AuditLog.Action.UPDATE, instance)

    def perform_destroy(self, instance):
        if self.audit_writes:
            record(self.request, AuditLog.Action.DELETE, instance)
        instance.delete()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if self.audit_reads:
            record(request, AuditLog.Action.VIEW, instance)
        return Response(self.get_serializer(instance).data)


class ClinicScopedGenericViewSet(ClinicScopedMixin, viewsets.GenericViewSet):
    pass


class ClinicScopedModelViewSet(ClinicScopedMixin, viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
