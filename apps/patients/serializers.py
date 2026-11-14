from rest_framework import serializers

from apps.core.validators import validate_phone
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
    is_lead = serializers.BooleanField(read_only=True)
    # Only on a leads-only search, to tell two people with the same name apart.
    last_appointment_at = serializers.DateTimeField(read_only=True, allow_null=True, default=None)

    class Meta:
        model = Patient
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "full_name",
            "phone_number",
            "birth_date",
            "workplace",
            "address",
            "notes",
            "primary_doctor",
            "primary_doctor_name",
            "archived_at",
            "created_at",
            "registered_at",
            "is_lead",
            "last_appointment_at",
            "debt",
        ]
        read_only_fields = ["id", "clinic", "archived_at", "created_at", "registered_at"]


class PatientSearchSerializer(serializers.Serializer):
    """Search text travels in the body so that names never reach access logs."""

    query = serializers.CharField(min_length=2, max_length=100)
    include_archived = serializers.BooleanField(default=False)
    # The booking dialog looks for leads too, so a returning caller is not entered twice.
    include_leads = serializers.BooleanField(default=False)
    # The "new patient" dialog offers only leads, so a booked person is registered, not entered twice.
    only_leads = serializers.BooleanField(default=False)


class LeadSerializer(serializers.Serializer):
    """The two things the desk asks someone who is only booking a visit."""

    full_name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=16, validators=[validate_phone])


class MedicalHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalHistory
        fields = ["allergies", "chronic_conditions", "current_medications", "is_pregnant", "notes", "updated_at"]
        read_only_fields = ["updated_at"]
