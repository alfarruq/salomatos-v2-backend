from django.db import transaction
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.billing.balance import annotate_balance
from apps.billing.models import Payment
from apps.billing.serializers import PatientBalanceSerializer, PaymentSerializer
from apps.dental.serializers import VoidSerializer
from apps.patients.access import ensure_patient_visible, patient_filter
from apps.patients.models import Patient
from apps.tenancy.viewsets import ClinicScopedMixin


class PaymentFilter(filters.FilterSet):
    patient = filters.UUIDFilter()
    paid_from = filters.IsoDateTimeFilter(field_name="paid_at", lookup_expr="gte")
    paid_to = filters.IsoDateTimeFilter(field_name="paid_at", lookup_expr="lt")
    voided = filters.BooleanFilter(field_name="voided_at", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Payment
        fields = ["method"]


class PaymentViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Payments are entered and voided, never edited or deleted."""

    queryset = Payment.objects.select_related("clinic", "patient", "received_by__user")
    serializer_class = PaymentSerializer
    filterset_class = PaymentFilter
    organization_actions = frozenset({"list", "retrieve"})
    required_permissions = {
        "list": "payment:view",
        "retrieve": "payment:view",
        "create": "payment:manage",
        "void": "payment:void",
    }

    def scope_queryset(self, queryset):
        return queryset.filter(patient_filter(self.request)).distinct()

    def perform_create(self, serializer):
        ensure_patient_visible(self.request, serializer.validated_data["patient"])
        serializer.validated_data["received_by"] = self.request.membership
        super().perform_create(serializer)

    @extend_schema(request=VoidSerializer, responses={200: PaymentSerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def void(self, request, pk=None):
        payment = self.get_object()
        params = VoidSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        if payment.voided_at is not None:
            raise ValidationError("Already voided.", code="already_voided")
        payment.voided_at = timezone.now()
        payment.voided_by = request.membership
        payment.void_reason = params.validated_data["reason"]
        payment.save()
        record(request, AuditLog.Action.UPDATE, payment)
        return Response(self.get_serializer(payment).data)


class BalanceFilter(filters.FilterSet):
    has_debt = filters.BooleanFilter(method="filter_has_debt")

    class Meta:
        model = Patient
        fields = []

    def filter_has_debt(self, queryset, name, value):
        return queryset.filter(debt__gt=0) if value else queryset.filter(debt__lte=0)


class PatientBalanceViewSet(
    ClinicScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """What each patient was charged, paid and still owes. `?has_debt=true` lists debtors."""

    queryset = Patient.objects.select_related("clinic")
    serializer_class = PatientBalanceSerializer
    filterset_class = BalanceFilter
    organization_actions = frozenset({"list", "retrieve"})
    required_permissions = {"list": "payment:view", "retrieve": "payment:view"}

    def scope_queryset(self, queryset):
        queryset = queryset.filter(patient_filter(self.request, prefix="")).distinct()
        return annotate_balance(queryset).order_by("-debt", "full_name")
