from rest_framework import serializers
from apps.calendars.models import Appointment
from apps.core.exceptions import ValidationError


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
    class Meta:
        model = Appointment
        fields = [
            'guest_name',
            'guest_phone',
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

