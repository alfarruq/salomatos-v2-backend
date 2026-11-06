from django.http import FileResponse
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.imaging.models import Attachment
from apps.imaging.serializers import AttachmentSerializer, AttachmentUpdateSerializer
from apps.patients.access import ensure_patient_visible, patient_filter
from apps.tenancy.viewsets import ClinicScopedModelViewSet


class AttachmentFilter(filters.FilterSet):
    patient = filters.UUIDFilter()
    tooth = filters.NumberFilter()

    class Meta:
        model = Attachment
        fields = ["kind"]


class AttachmentViewSet(ClinicScopedModelViewSet):
    queryset = Attachment.objects.select_related("clinic")
    filterset_class = AttachmentFilter
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    organization_actions = frozenset({"list", "retrieve", "download"})
    required_permissions = {
        "list": "attachment:view",
        "retrieve": "attachment:view",
        "download": "attachment:view",
        "create": "attachment:manage",
        "partial_update": "attachment:manage",
        "destroy": "attachment:manage",
    }

    def get_serializer_class(self):
        return AttachmentUpdateSerializer if self.action == "partial_update" else AttachmentSerializer

    def scope_queryset(self, queryset):
        return queryset.filter(patient_filter(self.request)).distinct()

    def perform_create(self, serializer):
        ensure_patient_visible(self.request, serializer.validated_data["patient"])
        serializer.validated_data["uploaded_by"] = self.request.membership
        super().perform_create(serializer)

    def perform_destroy(self, instance):
        storage, name = instance.file.storage, instance.file.name
        super().perform_destroy(instance)
        storage.delete(name)

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        attachment = self.get_object()
        record(request, AuditLog.Action.EXPORT, attachment)
        response = FileResponse(
            attachment.file.open("rb"),
            content_type=attachment.content_type or "application/octet-stream",
            filename=f"{attachment.kind}-{attachment.pk}{attachment.file.name[attachment.file.name.rfind('.') :]}",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
