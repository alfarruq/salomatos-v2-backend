from django.db import transaction
from rest_framework import serializers

from apps.clinical.models import Prescription, PrescriptionItem
from apps.patients.models import Patient
from apps.patients.serializers import doctor_field
from apps.tenancy.fields import ClinicRelatedField


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionItem
        fields = ["id", "medicine", "dose", "form", "times_per_day", "duration_days", "meal_relation", "instructions"]
        read_only_fields = ["id"]


class PrescriptionSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    patient = ClinicRelatedField(queryset=Patient.objects.all())
    doctor = doctor_field(required=False)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    items = PrescriptionItemSerializer(many=True)

    class Meta:
        model = Prescription
        fields = ["id", "clinic", "clinic_name", "patient", "doctor", "doctor_name", "notes", "items", "created_at"]
        read_only_fields = ["id", "clinic", "created_at"]

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one medicine.", code="required")
        return value

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        prescription = Prescription.objects.create(**validated_data)
        PrescriptionItem.objects.bulk_create(PrescriptionItem(prescription=prescription, **item) for item in items)
        return prescription

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            instance.items.all().delete()
            PrescriptionItem.objects.bulk_create(PrescriptionItem(prescription=instance, **item) for item in items)
        return instance
