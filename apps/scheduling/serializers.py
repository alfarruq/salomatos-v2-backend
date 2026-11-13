from datetime import timedelta

from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.catalog.models import Service
from apps.patients.models import Patient
from apps.patients.serializers import LeadSerializer, doctor_field
from apps.scheduling.models import Appointment, Chair
from apps.tenancy.fields import ClinicRelatedField


class ChairSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chair
        fields = ["id", "name", "is_active"]


class AppointmentSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    patient = ClinicRelatedField(
        queryset=Patient.objects.all(), extra_filter={"archived_at__isnull": True}, required=False
    )
    # Someone booking for the first time: stored as a lead, kept out of the patient list.
    new_patient = LeadSerializer(write_only=True, required=False)
    doctor = doctor_field()
    chair = ClinicRelatedField(
        queryset=Chair.objects.all(), extra_filter={"is_active": True}, required=False, allow_null=True
    )
    service = ClinicRelatedField(queryset=Service.objects.all(), required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "patient",
            "patient_name",
            "new_patient",
            "doctor",
            "doctor_name",
            "chair",
            "service",
            "start_at",
            "end_at",
            "status",
            "notes",
        ]
        read_only_fields = ["id", "clinic"]

    def validate(self, attrs):
        instance = self.instance
        if "new_patient" in attrs and (instance is not None or "patient" in attrs):
            raise serializers.ValidationError(
                {"new_patient": "Send either an existing patient or a new one, on create only."}, code="invalid"
            )
        if instance is None and "patient" not in attrs and "new_patient" not in attrs:
            raise serializers.ValidationError({"patient": "This field is required."}, code="required")
        start = attrs.get("start_at", getattr(instance, "start_at", None))
        end = attrs.get("end_at", getattr(instance, "end_at", None))
        service = attrs.get("service", getattr(instance, "service", None))
        if "start_at" in attrs and "end_at" not in attrs and instance is None:
            minutes = service.duration_minutes if service else 30
            end = start + timedelta(minutes=minutes)
            attrs["end_at"] = end
        if start and end and end <= start:
            raise serializers.ValidationError({"end_at": "Must be after the start."}, code="invalid_range")

        status = attrs.get("status", getattr(instance, "status", Appointment.Status.SCHEDULED))
        if status in Appointment.BLOCKING:
            self._check_conflicts(attrs, start, end)
        return attrs

    def create(self, validated_data):
        lead = validated_data.pop("new_patient", None)
        if lead is not None:
            request = self.context["request"]
            validated_data["patient"] = Patient.objects.create(clinic=request.clinic, registered_at=None, **lead)
            record(request, AuditLog.Action.CREATE, validated_data["patient"])
        return super().create(validated_data)

    def _check_conflicts(self, attrs, start, end):
        instance = self.instance
        doctor = attrs.get("doctor", getattr(instance, "doctor", None))
        chair = attrs.get("chair", getattr(instance, "chair", None))
        overlapping = Appointment.objects.filter(
            clinic=self.context["request"].clinic,
            status__in=Appointment.BLOCKING,
            start_at__lt=end,
            end_at__gt=start,
        )
        if instance is not None:
            overlapping = overlapping.exclude(pk=instance.pk)
        errors = {}
        if doctor and overlapping.filter(doctor=doctor).exists():
            errors["doctor"] = "The doctor already has an appointment at this time."
        if chair and overlapping.filter(chair=chair).exists():
            errors["chair"] = "The chair is taken at this time."
        if errors:
            raise serializers.ValidationError(errors, code="conflict")
