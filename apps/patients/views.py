from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.patients.access import patient_filter
from apps.patients.models import MedicalHistory, Patient
from apps.patients.serializers import MedicalHistorySerializer, PatientSearchSerializer, PatientSerializer
from apps.tenancy.viewsets import ClinicScopedMixin


class PatientFilter(filters.FilterSet):
    # Only non-PHI filters live in the query string; text search is POST /search/.
    primary_doctor = filters.UUIDFilter()
    archived = filters.BooleanFilter(field_name="archived_at", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Patient
        fields = ["primary_doctor", "gender"]


class PatientViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Patient.objects.select_related("clinic", "primary_doctor__user")
    serializer_class = PatientSerializer
    filterset_class = PatientFilter
    http_method_names = ["get", "post", "patch", "head", "options"]
    organization_actions = frozenset({"list", "retrieve", "search", "medical_history"})
    required_permissions = {
        "list": "patient:view",
        "retrieve": "patient:view",
        "search": "patient:view",
        "create": "patient:manage",
        "partial_update": "patient:manage",
        "archive": "patient:archive",
        "restore": "patient:archive",
        "medical_history": "patient:view",
        "update_medical_history": "patient:manage",
    }

    def scope_queryset(self, queryset):
        # A doctor sees patients assigned to them or booked with them.
        return queryset.filter(patient_filter(self.request, prefix="")).distinct()

    def _guard_primary_doctor(self, serializer):
        """A doctor registers patients to themselves and cannot hand one to a colleague.

        Otherwise a patient the doctor just added could vanish from their own
        list, and a doctor could move a patient between colleagues' lists.
        """
        if self.has_perm("patient:view_all"):
            return
        me = self.request.membership
        data = serializer.validated_data
        current = serializer.instance.primary_doctor if serializer.instance else None
        if serializer.instance is None and data.get("primary_doctor") is None:
            data["primary_doctor"] = me
        elif "primary_doctor" in data and data["primary_doctor"] not in (me, current):
            raise PermissionDenied("A doctor registers patients to themselves.")

    def perform_create(self, serializer):
        self._guard_primary_doctor(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._guard_primary_doctor(serializer)
        super().perform_update(serializer)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action == "list" and "archived" not in self.request.query_params:
            queryset = queryset.filter(archived_at__isnull=True)
        return queryset

    @extend_schema(request=PatientSearchSerializer, responses={200: PatientSerializer(many=True)})
    @action(detail=False, methods=["post"])
    def search(self, request):
        params = PatientSearchSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        text = params.validated_data["query"].strip()
        queryset = self.get_queryset().filter(Q(full_name__icontains=text) | Q(phone_number__icontains=text))
        if not params.validated_data["include_archived"]:
            queryset = queryset.filter(archived_at__isnull=True)
        page = self.paginate_queryset(queryset.order_by("full_name"))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(request=None, responses={200: PatientSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        patient = self.get_object()
        if patient.archived_at is None:
            patient.archived_at = timezone.now()
            patient.save(update_fields=["archived_at", "updated_at"])
            record(request, AuditLog.Action.ARCHIVE, patient)
        return Response(self.get_serializer(patient).data)

    @extend_schema(request=None, responses={200: PatientSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        patient = self.get_object()
        if patient.archived_at is not None:
            patient.archived_at = None
            patient.save(update_fields=["archived_at", "updated_at"])
            record(request, AuditLog.Action.RESTORE, patient)
        return Response(self.get_serializer(patient).data)

    @extend_schema(responses={200: MedicalHistorySerializer})
    @action(detail=True, methods=["get"], url_path="medical-history")
    def medical_history(self, request, pk=None):
        history = self._history(self.get_object())
        record(request, AuditLog.Action.VIEW, history)
        return Response(MedicalHistorySerializer(history).data)

    @extend_schema(request=MedicalHistorySerializer, responses={200: MedicalHistorySerializer})
    @medical_history.mapping.patch
    def update_medical_history(self, request, pk=None):
        history = self._history(self.get_object())
        serializer = MedicalHistorySerializer(history, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(request, AuditLog.Action.UPDATE, history)
        return Response(serializer.data)

    @staticmethod
    def _history(patient: Patient) -> MedicalHistory:
        history, _ = MedicalHistory.objects.get_or_create(patient=patient, defaults={"clinic": patient.clinic})
        return history
