from rest_framework import serializers
from apps.clinic.models import Clinic,SMS

class ClinicListSerializer(serializers.Serializer):
    admin = serializers.CharField()
    name = serializers.CharField()
    phone_number = serializers.CharField()
    address = serializers.CharField()
    logo = serializers.ImageField()
    working_hours = serializers.JSONField()



class ClinicCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = [
            'admin',
            'name',
            'phone_number',
            'address',
            'logo',
            'working_hours'
        ]


class SMSListSerializer(serializers.Serializer):
    balance = serializers.IntegerField()