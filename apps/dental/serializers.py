from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.catalog.models import Service
from apps.dental.models import SURFACES, PlanItem, Procedure, ToothEvent, ToothRecord, TreatmentPlan
from apps.patients.models import Patient
from apps.patients.serializers import doctor_field
from apps.scheduling.models import Appointment
from apps.tenancy.fields import ClinicRelatedField


def validate_surfaces(value):
    if not isinstance(value, list) or any(s not in SURFACES for s in value):
        raise serializers.ValidationError(f"Surfaces must be a list of {', '.join(SURFACES)}.", code="invalid")
    if len(set(value)) != len(value):
        raise serializers.ValidationError("Each surface may appear once.", code="invalid")
    return value


def require_tooth_for_surfaces(attrs, instance=None):
    tooth = attrs.get("tooth", getattr(instance, "tooth", None))
    if attrs.get("surfaces") and tooth is None:
        raise serializers.ValidationError({"surfaces": "Surfaces need a tooth."}, code="invalid")


class ToothRecordSerializer(serializers.ModelSerializer):
    patient = ClinicRelatedField(queryset=Patient.objects.all())
    surfaces = serializers.JSONField(required=False, validators=[validate_surfaces])

    class Meta:
        model = ToothRecord
        fields = ["id", "clinic", "patient", "tooth", "condition", "surfaces", "notes", "updated_at"]
        read_only_fields = ["id", "clinic", "updated_at"]
        # Upsert by (patient, tooth) happens in the view, not via a unique validator.
        validators = []


class ToothRecordUpdateSerializer(serializers.ModelSerializer):
    surfaces = serializers.JSONField(required=False, validators=[validate_surfaces])

    class Meta:
        model = ToothRecord
        fields = ["condition", "surfaces", "notes"]


class ToothEventSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source="recorded_by.user.full_name", read_only=True, default=None)

    class Meta:
        model = ToothEvent
        fields = ["id", "tooth", "condition", "surfaces", "notes", "recorded_by", "recorded_by_name", "created_at"]
        read_only_fields = fields


class PlanItemSerializer(serializers.ModelSerializer):
    service = ClinicRelatedField(queryset=Service.objects.all())
    service_name = serializers.CharField(source="service.name", read_only=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False)
    surfaces = serializers.JSONField(required=False, validators=[validate_surfaces])
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = PlanItem
        fields = [
            "id",
            "service",
            "service_name",
            "tooth",
            "surfaces",
            "phase",
            "quantity",
            "unit_price",
            "discount_percent",
            "total",
            "status",
            "notes",
        ]
        read_only_fields = ["id", "status"]

    def validate(self, attrs):
        require_tooth_for_surfaces(attrs)
        if attrs.get("unit_price") is None:
            attrs["unit_price"] = attrs["service"].price
        return attrs


class TreatmentPlanSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    patient = ClinicRelatedField(queryset=Patient.objects.all(), extra_filter={"archived_at__isnull": True})
    doctor = doctor_field(required=False)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    items = PlanItemSerializer(many=True, required=False)
    total = serializers.SerializerMethodField()

    class Meta:
        model = TreatmentPlan
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "patient",
            "doctor",
            "doctor_name",
            "title",
            "status",
            "notes",
            "accepted_at",
            "items",
            "total",
            "created_at",
        ]
        read_only_fields = ["id", "clinic", "status", "accepted_at", "created_at"]

    def get_total(self, obj) -> str:
        total = sum((item.total for item in obj.items.all() if item.status != PlanItem.Status.CANCELLED), start=0)
        return f"{total:.2f}"

    def validate(self, attrs):
        if self.instance is not None and self.instance.status not in TreatmentPlan.EDITABLE:
            raise serializers.ValidationError("An accepted or closed plan cannot be edited.", code="locked")
        if self.instance is not None and "patient" in attrs and attrs["patient"] != self.instance.patient:
            raise serializers.ValidationError({"patient": "A plan cannot move to another patient."}, code="locked")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        plan = TreatmentPlan.objects.create(**validated_data)
        PlanItem.objects.bulk_create(PlanItem(plan=plan, **item) for item in items)
        return plan

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            instance.items.all().delete()
            PlanItem.objects.bulk_create(PlanItem(plan=instance, **item) for item in items)
        return instance


class ProcedureSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    patient = ClinicRelatedField(queryset=Patient.objects.all(), extra_filter={"archived_at__isnull": True})
    # The clinic-wide procedure journal lists rows of many patients; without the name it is unreadable.
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    doctor = doctor_field(required=False)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    service = ClinicRelatedField(queryset=Service.objects.all())
    service_name = serializers.CharField(source="service.name", read_only=True)
    plan_item = ClinicRelatedField(
        queryset=PlanItem.objects.all(), clinic_lookup="plan__clinic", required=False, allow_null=True
    )
    appointment = ClinicRelatedField(queryset=Appointment.objects.all(), required=False, allow_null=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False)
    surfaces = serializers.JSONField(required=False, validators=[validate_surfaces])
    performed_at = serializers.DateTimeField(required=False)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Procedure
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "patient",
            "patient_name",
            "doctor",
            "doctor_name",
            "service",
            "service_name",
            "plan_item",
            "appointment",
            "tooth",
            "surfaces",
            "quantity",
            "unit_price",
            "discount_percent",
            "total",
            "performed_at",
            "notes",
            "voided_at",
            "void_reason",
        ]
        read_only_fields = ["id", "clinic", "voided_at", "void_reason"]

    def validate(self, attrs):
        require_tooth_for_surfaces(attrs)
        patient = attrs["patient"]
        plan_item = attrs.get("plan_item")
        if plan_item is not None:
            if plan_item.plan.patient_id != patient.pk:
                raise serializers.ValidationError(
                    {"plan_item": "This item belongs to another patient."}, code="invalid"
                )
            if plan_item.status != PlanItem.Status.PLANNED or hasattr(plan_item, "procedure"):
                raise serializers.ValidationError(
                    {"plan_item": "This item is already done or cancelled."}, code="invalid"
                )
            if plan_item.plan.status != TreatmentPlan.Status.ACCEPTED:
                raise serializers.ValidationError({"plan_item": "The plan is not accepted."}, code="invalid")
        appointment = attrs.get("appointment")
        if appointment is not None and appointment.patient_id != patient.pk:
            raise serializers.ValidationError({"appointment": "This appointment is another patient's."}, code="invalid")
        if plan_item is not None:
            # Performing a planned item charges what the patient agreed to.
            for field in ("unit_price", "discount_percent", "quantity", "tooth", "surfaces"):
                if attrs.get(field) in (None, []) or field not in self.initial_data:
                    attrs[field] = getattr(plan_item, field)
            attrs["service"] = plan_item.service
        elif attrs.get("unit_price") is None:
            attrs["unit_price"] = attrs["service"].price
        attrs.setdefault("performed_at", timezone.now())
        return attrs


class ProcedureUpdateSerializer(serializers.ModelSerializer):
    """Only the note can change: money fields are fixed once recorded (void and re-enter instead)."""

    class Meta:
        model = Procedure
        fields = ["notes"]


class VoidSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=255)
