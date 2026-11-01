from rest_framework import serializers
from apps.calendars.models import Appointment
from apps.core.exceptions import ValidationError
from apps.authentication.models import User


class AppointmentListSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    patient_id = serializers.IntegerField(read_only=True)
    patient = serializers.CharField(read_only=True)
    phone_number = serializers.CharField(source='patient.phone_number', read_only=True)
    doctor_id = serializers.IntegerField(read_only=True)
    doctor = serializers.CharField(read_only=True)
    date = serializers.DateField(read_only=True)
    time = serializers.TimeField(read_only=True)
    notes = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)

    treatment_type = serializers.CharField(read_only=True)
    tooth_number = serializers.IntegerField(read_only=True)



class AppointmentCreateUpdateSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(write_only=True, required=False, allow_null=True)
    phone_number = serializers.CharField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Appointment
        fields = [
            'full_name',
            'phone_number',
            'patient',
            'doctor',
            'date',
            'time',
            'notes',
            'status',
            'treatment_type',
            'tooth_number',
        ]
        extra_kwargs = {
            'patient': {'required': False, 'allow_null': True}
        }

    def create(self, validated_data):
        full_name = validated_data.pop('full_name', None)
        phone_number = validated_data.pop('phone_number', None)

        if full_name and phone_number:
            patient, _ = User.objects.get_or_create(
                phone_number=phone_number,
                clinic=validated_data['clinic'],
                role=User.Roles.PATIENT,
                defaults={
                    'full_name': full_name,
                    'is_origin': False,
                }
            )
            validated_data['patient'] = patient

        return super().create(validated_data)



    def validate(self, attrs):
        doctor = attrs.get('doctor', getattr(self.instance, 'doctor', None))
        date = attrs.get('date', getattr(self.instance, 'date', None))
        time = attrs.get('time', getattr(self.instance, 'time', None))

        busy = Appointment.objects.filter(doctor=doctor, date=date, time=time)
        if self.instance:
            busy = busy.exclude(pk=self.instance.pk)

        if busy.exists():
            raise ValidationError(
                message="This appointment time is busy",
                message_key='this_appointment_time_is_busy',

            )

        return attrs

