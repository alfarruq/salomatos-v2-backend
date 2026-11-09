from rest_framework import serializers

from apps.patients.models import MedicalHistory, Patient
from apps.tenancy.fields import ClinicRelatedField
from apps.tenancy.models import Membership


def doctor_field(**kwargs):
    return ClinicRelatedField(
        queryset=Membership.objects.all(),
        extra_filter={"role": Membership.Role.DOCTOR, "is_active": True},
        **kwargs,
    )


class PatientSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    primary_doctor = doctor_field(required=False, allow_null=True)
    primary_doctor_name = serializers.CharField(source="primary_doctor.user.full_name", read_only=True, default=None)
    # Charged minus paid; null when the caller may not see money or the row was not annotated.
    debt = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, allow_null=True, default=None)

    class Meta:
        model = Patient
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "full_name",
            "phone_number",
            "birth_date",
            "gender",
            "address",
            "notes",
            "primary_doctor",
            "primary_doctor_name",
            "archived_at",
            "created_at",
            "debt",
        ]
        read_only_fields = ["id", "clinic", "archived_at", "created_at"]


class PatientSearchSerializer(serializers.Serializer):
    """Search text travels in the body so that names never reach access logs."""

    query = serializers.CharField(min_length=2, max_length=100)
    include_archived = serializers.BooleanField(default=False)


class MedicalHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalHistory
        fields = ["allergies", "chronic_conditions", "current_medications", "is_pregnant", "notes", "updated_at"]
        read_only_fields = ["updated_at"]
