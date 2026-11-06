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
