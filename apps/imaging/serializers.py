from django.conf import settings
from rest_framework import serializers

from apps.imaging.models import Attachment
from apps.patients.models import Patient
from apps.tenancy.fields import ClinicRelatedField


class AttachmentSerializer(serializers.ModelSerializer):
    clinic_name = serializers.CharField(source="clinic.name", read_only=True)
    patient = ClinicRelatedField(queryset=Patient.objects.all())
    file = serializers.FileField(write_only=True)

    class Meta:
        model = Attachment
        fields = [
            "id",
            "clinic",
            "clinic_name",
            "patient",
            "kind",
            "tooth",
            "file",
            "content_type",
            "size_bytes",
            "taken_at",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "clinic", "content_type", "size_bytes", "created_at"]

    def validate_file(self, value):
        if value.size > settings.MAX_ATTACHMENT_BYTES:
            raise serializers.ValidationError("The file is too large.", code="file_too_large")
        return value

    def create(self, validated_data):
        upload = validated_data["file"]
        validated_data["content_type"] = getattr(upload, "content_type", "") or ""
        validated_data["size_bytes"] = upload.size
        return super().create(validated_data)


class AttachmentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["kind", "tooth", "taken_at", "notes"]
