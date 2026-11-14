import re

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record, record_many
from apps.billing.balance import annotate_balance
from apps.bot.credentials import issue_for_patient, reset
from apps.bot.serializers import BotAccessSerializer
from apps.bot.views import respond_with_access
from apps.patients.access import patient_filter
from apps.patients.models import MedicalHistory, Patient
from apps.patients.serializers import MedicalHistorySerializer, PatientSearchSerializer, PatientSerializer
from apps.scheduling.models import Appointment
from apps.tenancy.viewsets import ClinicScopedMixin


class PatientFilter(filters.FilterSet):
    # Only non-PHI filters live in the query string; text search is POST /search/.
    primary_doctor = filters.UUIDFilter()
    archived = filters.BooleanFilter(field_name="archived_at", lookup_expr="isnull", exclude=True)
    lead = filters.BooleanFilter(field_name="registered_at", lookup_expr="isnull")

    class Meta:
        model = Patient
        fields = ["primary_doctor"]


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
    organization_actions = frozenset({"list", "retrieve", "search", "medical_history", "bot_access"})
    required_permissions = {
        "list": "patient:view",
        "retrieve": "patient:view",
        "search": "patient:view",
        "create": "patient:manage",
        "partial_update": "patient:manage",
        "register": "patient:manage",
        "archive": "patient:archive",
        "restore": "patient:archive",
        "medical_history": "patient:view",
        "update_medical_history": "patient:manage",
        "bot_access": "patient:bot_access",
        "reset_bot_access": "patient:bot_access",
    }

    # The list shows each patient's debt so the desk sees it before booking.
    BALANCE_ACTIONS = frozenset({"list", "search", "retrieve"})

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in self.BALANCE_ACTIONS and self.has_perm("payment:view"):
            queryset = annotate_balance(queryset)
        return queryset

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

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        record_many(request, AuditLog.Action.VIEW, page)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action == "list" and "archived" not in self.request.query_params:
            queryset = queryset.filter(archived_at__isnull=True)
        if self.action == "list" and "lead" not in self.request.query_params:
            # Someone who only booked a visit is not a patient yet.
            queryset = queryset.filter(registered_at__isnull=False)
        return queryset

    @extend_schema(request=PatientSearchSerializer, responses={200: PatientSerializer(many=True)})
    @action(detail=False, methods=["post"])
    def search(self, request):
        params = PatientSearchSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        text = params.validated_data["query"].strip()
        # Every word must match, in any order: "Vali Aliyev" finds "Aliyev Vali".
        by_name = Q()
        for word in text.split():
            by_name &= Q(full_name__icontains=word)
        matches = by_name | Q(phone_number__icontains=text)
        # Phones are stored as +998XXXXXXXXX; staff type "91 108-71" or "(91) 108".
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 3:
            matches |= Q(phone_number__icontains=digits)
        queryset = self.get_queryset().filter(matches)
        if not params.validated_data["include_archived"]:
            queryset = queryset.filter(archived_at__isnull=True)
        if params.validated_data["only_leads"]:
            last = Appointment.objects.filter(patient=OuterRef("pk")).order_by("-start_at").values("start_at")[:1]
            queryset = queryset.filter(registered_at__isnull=True).annotate(last_appointment_at=Subquery(last))
        elif not params.validated_data["include_leads"]:
            queryset = queryset.filter(registered_at__isnull=False)
        page = self.paginate_queryset(queryset.order_by("full_name"))
        record_many(request, AuditLog.Action.VIEW, page)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(request=PatientSerializer, responses={200: PatientSerializer})
    @action(detail=True, methods=["post"])
    def register(self, request, pk=None):
        """Turns a lead into a patient: the desk fills the patient form at the first procedure."""
        patient = self.get_object()
        serializer = self.get_serializer(patient, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self._guard_primary_doctor(serializer)
        if patient.registered_at is None:
            serializer.validated_data["registered_at"] = timezone.now()
        serializer.save()
        record(request, AuditLog.Action.UPDATE, patient)
        return Response(serializer.data)

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

    @extend_schema(responses={200: BotAccessSerializer})
    @action(detail=True, methods=["get"], url_path="bot-access")
    def bot_access(self, request, pk=None):
        patient = self.get_object()
        return respond_with_access(request, issue_for_patient(patient), clinic=patient.clinic)

    @extend_schema(request=None, responses={200: BotAccessSerializer})
    @action(detail=True, methods=["post"], url_path="bot-access/reset")
    def reset_bot_access(self, request, pk=None):
        patient = self.get_object()
        account = reset(issue_for_patient(patient))
        record(request, AuditLog.Action.UPDATE, account, clinic=patient.clinic)
        return respond_with_access(request, account, clinic=patient.clinic)

    @staticmethod
    def _history(patient: Patient) -> MedicalHistory:
        history, _ = MedicalHistory.objects.get_or_create(patient=patient, defaults={"clinic": patient.clinic})
        return history
