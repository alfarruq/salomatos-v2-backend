from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from apps.tenancy.fields import ClinicRelatedField
from apps.tenancy.models import Clinic, Membership, Specialty
from apps.tenancy.permissions import permissions_for

User = get_user_model()


class ClinicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = ["id", "name", "phone_number", "address", "timezone", "working_hours", "is_active"]
        read_only_fields = ["id", "is_active"]


class ClinicBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = ["id", "name"]


class SpecialtySerializer(serializers.ModelSerializer):
    class Meta:
        model = Specialty
        fields = ["id", "name"]

    def validate_name(self, value):
        clinic = self.context["request"].clinic
        qs = Specialty.objects.filter(clinic=clinic, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A specialty with this name already exists.", code="duplicate")
        return value


class StaffSerializer(serializers.ModelSerializer):
    """A clinic employee: the membership plus the login it belongs to."""

    username = serializers.CharField(source="user.username")
    full_name = serializers.CharField(source="user.full_name")
    phone_number = serializers.CharField(source="user.phone_number", required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})
    specialty = ClinicRelatedField(queryset=Specialty.objects.all(), required=False, allow_null=True)
    specialty_name = serializers.CharField(source="specialty.name", read_only=True, default=None)

    class Meta:
        model = Membership
        fields = [
            "id",
            "username",
            "full_name",
            "phone_number",
            "email",
            "password",
            "role",
            "is_active",
            "specialty",
            "specialty_name",
            "experience_years",
            "biography",
        ]
        read_only_fields = ["id", "is_active"]

    def validate_username(self, value):
        qs = User.objects.filter(username__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("This username is taken.", code="duplicate")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_role(self, value):
        request = self.context["request"]
        touches_owner = value == Membership.Role.OWNER or (
            self.instance is not None and self.instance.role == Membership.Role.OWNER
        )
        if touches_owner and "staff:manage_owners" not in permissions_for(request.membership):
            raise serializers.ValidationError("Only an owner can grant or change the owner role.", code="forbidden")
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "This field is required."}, code="required")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop("user")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **user_data)
        return Membership.objects.create(user=user, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        password = validated_data.pop("password", None)
        user = instance.user
        for field, value in user_data.items():
            setattr(user, field, value)
        if password:
            user.set_password(password)
        user.save()
        return super().update(instance, validated_data)


class MembershipSummarySerializer(serializers.ModelSerializer):
    clinic = ClinicBriefSerializer(read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "clinic", "role", "permissions"]

    def get_permissions(self, obj) -> list[str]:
        return sorted(permissions_for(obj))
