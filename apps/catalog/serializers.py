from rest_framework import serializers

from apps.catalog.models import Service, ServiceCategory
from apps.tenancy.fields import ClinicRelatedField
from apps.tenancy.models import Specialty


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "name"]


class ServiceSerializer(serializers.ModelSerializer):
    category = ClinicRelatedField(queryset=ServiceCategory.objects.all(), required=False, allow_null=True)
    specialty = ClinicRelatedField(queryset=Specialty.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Service
        fields = ["id", "code", "name", "category", "specialty", "price", "duration_minutes", "is_active"]
        read_only_fields = ["id"]
