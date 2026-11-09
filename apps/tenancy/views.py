from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from apps.accounts.sessions import revoke_all_sessions
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.bot.serializers import BotAccessSerializer
from apps.bot.views import respond_with_access
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
    queryset = Membership.objects.select_related("user", "specialty", "clinic").prefetch_related("compensations")
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
        "bot_access": "staff:manage",
        "reset_bot_access": "staff:manage",
    }

    def _guard_owner(self, membership):
        if membership.role == Membership.Role.OWNER and "staff:manage_owners" not in permissions_for(
            self.request.membership
        ):
            raise PermissionDenied("Only an owner can change an owner's account.")

    def perform_update(self, serializer):
        self._guard_owner(serializer.instance)
        data = serializer.validated_data
        changes_login = bool(data.get("password")) or "username" in data.get("user", {})
        if changes_login:
            self._guard_shared_login(serializer.instance)
        super().perform_update(serializer)
        if data.get("password"):
            revoke_all_sessions(serializer.instance.user)

    def _guard_shared_login(self, membership):
        # One login can belong to clinics of several organizations. Its password
        # opens all of them, so only an organization holding every one may set it.
        organization_id = self.request.clinic.organization_id
        if (
            Membership.objects.filter(user_id=membership.user_id)
            .exclude(clinic__organization_id=organization_id)
            .exists()
        ):
            raise PermissionDenied("This login is also used by another organization.")

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

    def _bot_account(self, membership):
        from apps.bot.credentials import issue_for_user
        from apps.bot.signals import BOT_ROLES

        # Admins have no bot login; asking for one is the same as asking for nothing.
        if membership.role not in BOT_ROLES or not membership.is_active:
            raise NotFound()
        return issue_for_user(membership.user)

    @extend_schema(responses={200: BotAccessSerializer})
    @action(detail=True, methods=["get"], url_path="bot-access")
    def bot_access(self, request, pk=None):
        membership = self.get_object()
        self._guard_owner(membership)
        return respond_with_access(request, self._bot_account(membership), clinic=membership.clinic)

    @extend_schema(request=None, responses={200: BotAccessSerializer})
    @action(detail=True, methods=["post"], url_path="bot-access/reset")
    def reset_bot_access(self, request, pk=None):
        from apps.bot.credentials import reset

        membership = self.get_object()
        self._guard_owner(membership)
        account = reset(self._bot_account(membership))
        record(request, AuditLog.Action.UPDATE, account, clinic=membership.clinic)
        return respond_with_access(request, account, clinic=membership.clinic)
