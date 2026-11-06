from rest_framework import generics, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenancy.models import Membership, Specialty
from apps.tenancy.permissions import permissions_for
from apps.tenancy.serializers import ClinicSerializer, SpecialtySerializer, StaffSerializer
from apps.tenancy.viewsets import ClinicScopedMixin, ClinicScopedModelViewSet


class CurrentClinicView(ClinicScopedMixin, generics.GenericAPIView):
    """The clinic named by `X-Clinic-Id`. There is no endpoint that lists other tenants."""

    serializer_class = ClinicSerializer
    required_permissions = {"get": "clinic:view", "patch": "clinic:manage"}

    def get(self, request):
        return Response(self.get_serializer(request.clinic).data)

    def patch(self, request):
        serializer = self.get_serializer(request.clinic, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(request, AuditLog.Action.UPDATE, request.clinic)
        return Response(serializer.data)


class SpecialtyViewSet(ClinicScopedModelViewSet):
    queryset = Specialty.objects.all()
    serializer_class = SpecialtySerializer
    pagination_class = None
    audit_reads = False
    required_permissions = {
        "list": "staff:view",
        "retrieve": "staff:view",
        "create": "specialty:manage",
        "partial_update": "specialty:manage",
        "destroy": "specialty:manage",
    }


class StaffViewSet(ClinicScopedModelViewSet):
    queryset = Membership.objects.select_related("user", "specialty")
    serializer_class = StaffSerializer
    audit_reads = False
    filterset_fields = ["role", "is_active", "specialty"]
    required_permissions = {
        "list": "staff:view",
        "retrieve": "staff:view",
        "create": "staff:manage",
        "partial_update": "staff:manage",
        "destroy": "staff:manage",
        "reactivate": "staff:manage",
    }

    def _guard_owner(self, membership):
        if membership.role == Membership.Role.OWNER and "staff:manage_owners" not in permissions_for(
            self.request.membership
        ):
            raise PermissionDenied("Only an owner can change an owner's account.")

    def perform_update(self, serializer):
        self._guard_owner(serializer.instance)
        super().perform_update(serializer)

    def destroy(self, request, *args, **kwargs):
        # Staff are deactivated, not deleted: their name stays on past visits.
        membership = self.get_object()
        self._guard_owner(membership)
        if membership.pk == request.membership.pk:
            raise PermissionDenied("You cannot deactivate your own account.")
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        record(request, AuditLog.Action.ARCHIVE, membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        membership = self.get_object()
        self._guard_owner(membership)
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
        record(request, AuditLog.Action.RESTORE, membership)
        return Response(self.get_serializer(membership).data)
