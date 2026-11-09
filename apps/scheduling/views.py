from django.db import transaction
from django_filters import rest_framework as filters
from rest_framework.exceptions import PermissionDenied

from apps.patients.access import ensure_patient_visible
from apps.scheduling.models import Appointment, Chair
from apps.scheduling.serializers import AppointmentSerializer, ChairSerializer
from apps.tenancy.viewsets import ClinicScopedModelViewSet


class AppointmentFilter(filters.FilterSet):
    start_from = filters.IsoDateTimeFilter(field_name="start_at", lookup_expr="gte")
    start_to = filters.IsoDateTimeFilter(field_name="start_at", lookup_expr="lt")
    doctor = filters.UUIDFilter()
    chair = filters.UUIDFilter()
    patient = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=Appointment.Status.choices)

    class Meta:
        model = Appointment
        fields = []


class ChairViewSet(ClinicScopedModelViewSet):
    queryset = Chair.objects.all()
    serializer_class = ChairSerializer
    pagination_class = None
    audit_reads = False
    required_permissions = {
        "list": "appointment:view",
        "retrieve": "appointment:view",
        "create": "chair:manage",
        "partial_update": "chair:manage",
        "destroy": "chair:manage",
    }


class AppointmentViewSet(ClinicScopedModelViewSet):
    queryset = Appointment.objects.select_related("clinic", "patient", "doctor__user", "chair", "service")
    serializer_class = AppointmentSerializer
    filterset_class = AppointmentFilter
    # No DELETE: a booking is cancelled (status), so no-shows and cancellations stay countable.
    http_method_names = ["get", "post", "patch", "head", "options"]
    organization_actions = frozenset({"list", "retrieve"})
    required_permissions = {
        "list": "appointment:view",
        "retrieve": "appointment:view",
        "create": "appointment:manage",
        "partial_update": "appointment:manage",
    }

    def scope_queryset(self, queryset):
        if self.has_perm("appointment:view_all"):
            return queryset
        return queryset.filter(doctor=self.request.membership)

    def _guard_doctor(self, serializer):
        # Without view_all a doctor manages only their own calendar.
        doctor = serializer.validated_data.get("doctor")
        if doctor is not None and not self.has_perm("appointment:view_all") and doctor != self.request.membership:
            raise PermissionDenied("You can only book appointments for yourself.")

    def _guard_patient(self, serializer):
        # A booking makes the patient visible to its doctor (`patient_filter`),
        # so booking a colleague's patient would open their whole record.
        patient = serializer.validated_data.get("patient")
        if patient is not None and (serializer.instance is None or patient != serializer.instance.patient):
            ensure_patient_visible(self.request, patient)

    @transaction.atomic
    def perform_create(self, serializer):
        self._guard_doctor(serializer)
        self._guard_patient(serializer)
        super().perform_create(serializer)

    @transaction.atomic
    def perform_update(self, serializer):
        self._guard_doctor(serializer)
        self._guard_patient(serializer)
        super().perform_update(serializer)
