from rest_framework import serializers

from apps.clinical.models import PrescriptionItem
from apps.patients.models import Patient
from apps.tenancy.fields import ClinicRelatedField
from apps.voice.drafts import FORMS


class VoiceDraftRequestSerializer(serializers.Serializer):
    """The dictation travels in the body: it is PHI and must not reach access logs."""

    form = serializers.ChoiceField(choices=sorted(FORMS))
    text = serializers.CharField(min_length=3, max_length=4000)
    # Set when the form already has its patient, e.g. opened from the patient card.
    patient = ClinicRelatedField(queryset=Patient.objects.all(), required=False, allow_null=True)


class DraftPatientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class DraftPatientFieldsSerializer(serializers.Serializer):
    full_name = serializers.CharField(allow_blank=True)
    phone_number = serializers.CharField(allow_blank=True)
    birth_date = serializers.DateField(allow_null=True)
    workplace = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)


class DraftProcedureSerializer(serializers.Serializer):
    service = serializers.UUIDField(allow_null=True)
    service_name = serializers.CharField(allow_blank=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    heard = serializers.CharField(
        allow_blank=True, help_text="The treatment as dictated, shown when no service matched."
    )
    tooth = serializers.IntegerField(allow_null=True)


class DraftMedicineSerializer(serializers.Serializer):
    medicine = serializers.CharField(allow_blank=True)
    dose = serializers.CharField(allow_blank=True)
    form = serializers.CharField(allow_blank=True)
    times_per_day = serializers.IntegerField(allow_null=True)
    duration_days = serializers.IntegerField(allow_null=True)
    meal_relation = serializers.ChoiceField(choices=PrescriptionItem.MealRelation.choices)
    instructions = serializers.CharField(allow_blank=True)


class VoiceDraftSerializer(serializers.Serializer):
    """A suggestion only. Nothing is saved; the doctor submits the real form."""

    form = serializers.ChoiceField(choices=sorted(FORMS))
    patient = DraftPatientSerializer(allow_null=True)
    patient_name = serializers.CharField(allow_blank=True, help_text="The name as dictated.")
    patient_candidates = DraftPatientSerializer(many=True)
    patient_fields = DraftPatientFieldsSerializer(allow_null=True)
    procedures = DraftProcedureSerializer(many=True)
    medicines = DraftMedicineSerializer(many=True)
    notes = serializers.CharField(allow_blank=True)


class VoiceStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    subscribed = serializers.BooleanField()
    paid_until = serializers.DateField(allow_null=True)
    used_this_month = serializers.IntegerField()
    monthly_limit = serializers.IntegerField()
