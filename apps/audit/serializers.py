from rest_framework import serializers

from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "created_at", "actor", "actor_name", "action", "target_type", "target_id"]
        read_only_fields = fields
