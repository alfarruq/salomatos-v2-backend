from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets

from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer
from apps.tenancy.viewsets import ClinicScopedMixin


class AuditLogFilter(filters.FilterSet):
    target_id = filters.UUIDFilter()
    target_type = filters.CharFilter()
    actor = filters.UUIDFilter()
    created_from = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_to = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lt")

    class Meta:
        model = AuditLog
        fields = ["action"]


class AuditLogViewSet(ClinicScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    filterset_class = AuditLogFilter
    required_permissions = {"list": "audit:view"}
    # Reading the audit trail is not itself audited; it holds no PHI.
    audit_reads = False
