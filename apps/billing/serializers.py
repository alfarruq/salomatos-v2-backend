from django.utils import timezone
from rest_framework import serializers

from apps.billing.models import Payment
from apps.patients.models import Patient
from apps.tenancy.fields import ClinicRelatedField


class PaymentSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    patient = ClinicRelatedField(queryset=Patient.objects.all())
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    received_by_name = serializers.CharField(source="received_by.user.full_name", read_only=True)
    paid_at = serializers.DateTimeField(required=False)

    class Meta:
        model = Payment
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "patient",
            "patient_name",
            "amount",
            "method",
            "paid_at",
            "received_by",
            "received_by_name",
            "notes",
            "voided_at",
            "void_reason",
        ]
        read_only_fields = ["id", "clinic", "received_by", "voided_at", "void_reason"]

    def validate(self, attrs):
        attrs.setdefault("paid_at", timezone.now())
        if attrs["paid_at"] > timezone.now():
            raise serializers.ValidationError({"paid_at": "A payment cannot be in the future."}, code="invalid")
        return attrs


class PatientBalanceSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    charged = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    paid = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    debt = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Patient
        fields = ["id", "clinic", "clinic_name", "full_name", "phone_number", "charged", "paid", "debt"]
        read_only_fields = fields
