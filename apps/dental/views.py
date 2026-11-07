from django.db import transaction
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.core.pagination import DefaultPagination
from apps.dental.models import PlanItem, Procedure, ToothEvent, ToothRecord, TreatmentPlan
from apps.dental.serializers import (
    ProcedureSerializer,
    ProcedureUpdateSerializer,
    ToothEventSerializer,
    ToothRecordSerializer,
    ToothRecordUpdateSerializer,
    TreatmentPlanSerializer,
    VoidSerializer,
)
from apps.patients.access import ensure_patient_visible, patient_filter
from apps.tenancy.viewsets import ClinicScopedMixin, ClinicScopedModelViewSet


class PatientRecordFilter(filters.FilterSet):
    patient = filters.UUIDFilter()


class ToothRecordFilter(PatientRecordFilter):
    tooth = filters.NumberFilter()

    class Meta:
        model = ToothRecord
        fields = ["condition"]


class ToothRecordViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """The dental chart. POST upserts one tooth; every change is kept in `history`."""

    queryset = ToothRecord.objects.all()
    filterset_class = ToothRecordFilter
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]
    organization_actions = frozenset({"list", "retrieve", "history"})
    required_permissions = {
        "list": "chart:view",
        "retrieve": "chart:view",
        "history": "chart:view",
        "create": "chart:manage",
        "partial_update": "chart:manage",
    }

    def get_serializer_class(self):
        return ToothRecordUpdateSerializer if self.action == "partial_update" else ToothRecordSerializer

    def scope_queryset(self, queryset):
        return queryset.filter(patient_filter(self.request)).distinct()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = ToothRecordSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ensure_patient_visible(request, data["patient"])
        record_, created = ToothRecord.objects.update_or_create(
            patient=data["patient"],
            tooth=data["tooth"],
            defaults={
                "clinic": request.clinic,
                "condition": data["condition"],
                "surfaces": data.get("surfaces", []),
                "notes": data.get("notes", ""),
                "updated_by": request.membership,
            },
        )
        self._log(record_, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE)
        return Response(
            ToothRecordSerializer(record_, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @transaction.atomic
    def perform_update(self, serializer):
        record_ = serializer.save(updated_by=self.request.membership)
        self._log(record_, AuditLog.Action.UPDATE)

    def _log(self, record_, action_):
        ToothEvent.objects.create(
            clinic=record_.clinic,
            patient=record_.patient,
            tooth=record_.tooth,
            condition=record_.condition,
            surfaces=record_.surfaces,
            notes=record_.notes,
            recorded_by=self.request.membership,
        )
        record(self.request, action_, record_)

    @extend_schema(responses={200: ToothEventSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def history(self, request):
        patient_id = request.query_params.get("patient")
        if not patient_id:
            raise ValidationError({"patient": "This parameter is required."}, code="required")
        events = ToothEvent.objects.filter(clinic_id__in=request.clinic_ids, patient_id=patient_id).filter(
            patient_filter(request)
        )
        if tooth := request.query_params.get("tooth"):
            events = events.filter(tooth=tooth)
        events = events.select_related("recorded_by__user").distinct().order_by("-created_at")
        # The chart itself is unpaginated (32 teeth at most); its history grows, so it pages.
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(events, request, view=self)
        return paginator.get_paginated_response(ToothEventSerializer(page, many=True).data)


class TreatmentPlanFilter(PatientRecordFilter):
    doctor = filters.UUIDFilter()

    class Meta:
        model = TreatmentPlan
        fields = ["status"]


class TreatmentPlanViewSet(ClinicScopedModelViewSet):
    queryset = TreatmentPlan.objects.select_related("clinic", "doctor__user").prefetch_related("items__service")
    serializer_class = TreatmentPlanSerializer
    filterset_class = TreatmentPlanFilter
    organization_actions = frozenset({"list", "retrieve"})
    required_permissions = {
        "list": "plan:view",
        "retrieve": "plan:view",
        "create": "plan:manage",
        "partial_update": "plan:manage",
        "destroy": "plan:manage",
        "present": "plan:manage",
        "accept": "plan:manage",
        "cancel": "plan:manage",
    }

    def scope_queryset(self, queryset):
        return queryset.filter(patient_filter(self.request)).distinct()

    def perform_create(self, serializer):
        ensure_patient_visible(self.request, serializer.validated_data["patient"])
        self.assign_doctor(serializer)
        super().perform_create(serializer)

    def perform_destroy(self, instance):
        if instance.status != TreatmentPlan.Status.DRAFT:
            raise ValidationError("Only a draft plan can be deleted; cancel it instead.", code="locked")
        super().perform_destroy(instance)

    def _transition(self, request, allowed_from, to, **extra):
        plan = self.get_object()
        if plan.status not in allowed_from:
            raise ValidationError(f"A {plan.status} plan cannot become {to}.", code="invalid_transition")
        plan.status = to
        for field, value in extra.items():
            setattr(plan, field, value)
        plan.save()
        record(request, AuditLog.Action.UPDATE, plan)
        return Response(self.get_serializer(plan).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def present(self, request, pk=None):
        return self._transition(request, [TreatmentPlan.Status.DRAFT], TreatmentPlan.Status.PRESENTED)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        plan = self.get_object()
        if not plan.items.exists():
            raise ValidationError("Add at least one item before accepting.", code="empty_plan")
        return self._transition(
            request, TreatmentPlan.EDITABLE, TreatmentPlan.Status.ACCEPTED, accepted_at=timezone.now()
        )

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            response = self._transition(
                request,
                [*TreatmentPlan.EDITABLE, TreatmentPlan.Status.ACCEPTED],
                TreatmentPlan.Status.CANCELLED,
            )
            PlanItem.objects.filter(plan_id=pk, status=PlanItem.Status.PLANNED).update(status=PlanItem.Status.CANCELLED)
        return response


class ProcedureFilter(PatientRecordFilter):
    doctor = filters.UUIDFilter()
    tooth = filters.NumberFilter()
    performed_from = filters.IsoDateTimeFilter(field_name="performed_at", lookup_expr="gte")
    performed_to = filters.IsoDateTimeFilter(field_name="performed_at", lookup_expr="lt")
    voided = filters.BooleanFilter(field_name="voided_at", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Procedure
        fields = ["service", "status"]


class ProcedureViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Procedure.objects.select_related("clinic", "patient", "doctor__user", "service")
    filterset_class = ProcedureFilter
    http_method_names = ["get", "post", "patch", "head", "options"]
    organization_actions = frozenset({"list", "retrieve"})
    required_permissions = {
        "list": "procedure:view",
        "retrieve": "procedure:view",
        "create": "procedure:manage",
        "partial_update": "procedure:manage",
        "complete": "procedure:manage",
        "void": "procedure:void",
    }

    def get_serializer_class(self):
        return ProcedureUpdateSerializer if self.action == "partial_update" else ProcedureSerializer

    def scope_queryset(self, queryset):
        queryset = queryset.filter(patient_filter(self.request)).distinct()
        if self.has_perm("patient:view_all") or self.request.query_params.get("patient"):
            # One patient's history is the whole of it: the next doctor needs
            # to know what a colleague already did to that tooth.
            return queryset
        # The treatments list is a doctor's own work.
        return queryset.filter(doctor=self.request.membership)

    def _ensure_own(self, procedure):
        if not self.has_perm("patient:view_all") and procedure.doctor_id != self.request.membership.pk:
            raise PermissionDenied("You can only change your own procedures.")

    def perform_update(self, serializer):
        self._ensure_own(serializer.instance)
        super().perform_update(serializer)

    @transaction.atomic
    def perform_create(self, serializer):
        ensure_patient_visible(self.request, serializer.validated_data["patient"])
        self.assign_doctor(serializer)
        if serializer.validated_data.get("status") != Procedure.Status.IN_PROGRESS:
            serializer.validated_data["completed_by"] = self.request.membership
        super().perform_create(serializer)
        if serializer.instance.status == Procedure.Status.COMPLETED:
            self._close_plan_item(serializer.instance)

    @staticmethod
    def _close_plan_item(procedure):
        # A plan item is done only when its work is finished, not when it starts.
        plan_item = procedure.plan_item
        if plan_item is None:
            return
        plan_item.status = PlanItem.Status.DONE
        plan_item.save(update_fields=["status", "updated_at"])
        plan = plan_item.plan
        if not plan.items.filter(status=PlanItem.Status.PLANNED).exists():
            plan.status = TreatmentPlan.Status.COMPLETED
            plan.save(update_fields=["status", "updated_at"])

    @extend_schema(request=None, responses={200: ProcedureSerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def complete(self, request, pk=None):
        procedure = self.get_object()
        self._ensure_own(procedure)
        if procedure.voided_at is not None:
            raise ValidationError("A voided procedure cannot be completed.", code="voided")
        if procedure.status == Procedure.Status.COMPLETED:
            raise ValidationError("Already completed.", code="already_completed")
        procedure.status = Procedure.Status.COMPLETED
        procedure.completed_at = timezone.now()
        procedure.completed_by = request.membership
        procedure.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
        self._close_plan_item(procedure)
        record(request, AuditLog.Action.UPDATE, procedure)
        return Response(ProcedureSerializer(procedure, context=self.get_serializer_context()).data)

    @extend_schema(request=VoidSerializer, responses={200: ProcedureSerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def void(self, request, pk=None):
        procedure = self.get_object()
        params = VoidSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        if procedure.voided_at is not None:
            raise ValidationError("Already voided.", code="already_voided")
        procedure.voided_at = timezone.now()
        procedure.voided_by = request.membership
        procedure.void_reason = params.validated_data["reason"]
        procedure.save()
        if procedure.plan_item_id:
            # The work is undone on paper, so the plan item is open again.
            PlanItem.objects.filter(pk=procedure.plan_item_id).update(status=PlanItem.Status.PLANNED)
            TreatmentPlan.objects.filter(
                items__pk=procedure.plan_item_id, status=TreatmentPlan.Status.COMPLETED
            ).update(status=TreatmentPlan.Status.ACCEPTED)
            procedure.plan_item = None
            procedure.save(update_fields=["plan_item", "updated_at"])
        record(request, AuditLog.Action.UPDATE, procedure)
        return Response(ProcedureSerializer(procedure, context=self.get_serializer_context()).data)
