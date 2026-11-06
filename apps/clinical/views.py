from django.http import HttpResponse
from django.template.loader import render_to_string
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.clinical.models import Prescription
from apps.clinical.serializers import PrescriptionSerializer
from apps.patients.access import ensure_patient_visible
from apps.tenancy.models import Membership
from apps.tenancy.viewsets import ClinicScopedModelViewSet


class PrescriptionFilter(filters.FilterSet):
    patient = filters.UUIDFilter()
    doctor = filters.UUIDFilter()

    class Meta:
        model = Prescription
        fields = []


class PrescriptionViewSet(ClinicScopedModelViewSet):
    queryset = Prescription.objects.select_related("clinic", "doctor__user", "patient").prefetch_related("items")
    serializer_class = PrescriptionSerializer
    filterset_class = PrescriptionFilter
    organization_actions = frozenset({"list", "retrieve", "pdf"})
    required_permissions = {
        "list": "prescription:view",
        "retrieve": "prescription:view",
        "pdf": "prescription:view",
        "create": "prescription:manage",
        "partial_update": "prescription:manage",
        "destroy": "prescription:manage",
    }

    def scope_queryset(self, queryset):
        if self.has_perm("patient:view_all"):
            return queryset
        return queryset.filter(doctor=self.request.membership)

    def perform_create(self, serializer):
        ensure_patient_visible(self.request, serializer.validated_data["patient"])
        me = self.request.membership
        doctor = serializer.validated_data.get("doctor")
        if doctor is None:
            if me.role != Membership.Role.DOCTOR:
                raise PermissionDenied("Choose the prescribing doctor.")
            serializer.validated_data["doctor"] = me
        elif not self.has_perm("patient:view_all") and doctor != me:
            raise PermissionDenied("You can only prescribe as yourself.")
        super().perform_create(serializer)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        from weasyprint import HTML

        prescription = self.get_object()
        html = render_to_string(
            "prescription_pdf.html",
            {"prescription": prescription, "clinic": prescription.clinic, "items": prescription.items.all()},
        )
        record(request, AuditLog.Action.EXPORT, prescription)
        response = HttpResponse(HTML(string=html).write_pdf(), content_type="application/pdf")
        # The file name carries the id only, never the patient's name.
        response["Content-Disposition"] = f'inline; filename="prescription-{prescription.pk}.pdf"'
        response["Cache-Control"] = "no-store"
        return response
