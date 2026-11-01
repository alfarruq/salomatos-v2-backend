from rest_framework import serializers
from apps.clinic.models import Treatment, TreatmentType
from django.db import transaction

class TreatmentListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    patient = serializers.CharField()
    patient_id = serializers.IntegerField()
    doctor = serializers.CharField()
    treatment_type = serializers.CharField()
    total_treatment_cost = serializers.IntegerField()
    total_paid = serializers.IntegerField()
    remaining = serializers.SerializerMethodField()
    visit_number = serializers.IntegerField()
    tooth_number = serializers.IntegerField()
    start_date = serializers.DateField()
    notes = serializers.CharField()
    status = serializers.CharField()

    def get_remaining(self, obj):
        return obj.total_treatment_cost - obj.total_paid

class TreatmentBulkCreateListSerializer(serializers.ListSerializer):
    @transaction.atomic
    def create(self, validated_data):
        treatments = [Treatment(**item) for item in validated_data]
        return Treatment.objects.bulk_create(treatments)

class TreatmentCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Treatment
        list_serializer_class = TreatmentBulkCreateListSerializer
        fields = [
            'patient',
            'doctor',
            'treatment_type',
            'total_treatment_cost',
            'total_paid',
            'visit_number',
            'tooth_number',
            'start_date',
            'notes',
            'status',
        ]

class TreatmentTypeListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.IntegerField()
    doctor_type = serializers.CharField()

class TreatmentTypeCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TreatmentType
        fields = [
            'name',
            'price',
            'doctor_type'
        ]
