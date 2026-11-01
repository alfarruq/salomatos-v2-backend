from rest_framework import serializers
from apps.core.models import (
    Recipe,
    Medicine
)

class MedicineListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    dose = serializers.IntegerField()
    type = serializers.CharField()
    frequency = serializers.CharField()
    duration = serializers.IntegerField()
    meal = serializers.CharField()
    minutes = serializers.IntegerField()

class RecipeListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    patient = serializers.CharField()
    doctor = serializers.CharField()
    notes = serializers.CharField()
    clinic = serializers.CharField()
    created_at = serializers.DateTimeField()
    medicines = MedicineListSerializer(many=True,read_only=True)

class MedicineCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Medicine
        fields = [
            'id',
            'name',
            'dose',
            'type',
            'frequency',
            'duration',
            'meal',
            'minutes',
        ]

class RecipeCreateUpdateSerializer(serializers.ModelSerializer):
    medicines = MedicineCreateUpdateSerializer(many=True)

    class Meta:
        model = Recipe
        fields = [
            'patient',
            'doctor',
            'notes',
            'medicines',
        ]

    def create(self, validated_data):
        medicines_data = validated_data.pop('medicines', [])

        recipe = Recipe.objects.create(**validated_data)

        medicine_objects = [
            Medicine(recipe=recipe, **medicine_data)
            for medicine_data in medicines_data
        ]

        if medicine_objects:
            Medicine.objects.bulk_create(medicine_objects)

        return recipe

