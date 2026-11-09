from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.catalog.models import Service, ServiceCategory
from apps.catalog.serializers import ServiceCategorySerializer, ServiceSerializer
from apps.tenancy.viewsets import ClinicScopedModelViewSet

_PERMS = {
    "list": "service:view",
    "retrieve": "service:view",
    "create": "service:manage",
    "partial_update": "service:manage",
    "destroy": "service:manage",
}


class ServiceCategoryViewSet(ClinicScopedModelViewSet):
    queryset = ServiceCategory.objects.all()
    serializer_class = ServiceCategorySerializer
    pagination_class = None
    required_permissions = _PERMS
    audit_reads = False


class ServiceViewSet(ClinicScopedModelViewSet):
    queryset = Service.objects.select_related("category")
    serializer_class = ServiceSerializer
    filterset_fields = ["category", "specialty", "is_active"]
    required_permissions = _PERMS
    audit_reads = False

    def perform_destroy(self, instance):
        from apps.dental.models import PlanItem, Procedure

        if Procedure.objects.filter(service=instance).exists() or PlanItem.objects.filter(service=instance).exists():
            # Procedures and plans keep pointing at it (their prices are history),
            # so a used service leaves the price list instead of the database.
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])
            record(self.request, AuditLog.Action.ARCHIVE, instance)
            return
        super().perform_destroy(instance)
