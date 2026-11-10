from django.contrib.auth import authenticate
from rest_framework import serializers

from apps.accounts.models import User
from apps.tenancy.models import Membership
from apps.tenancy.serializers import MembershipSummarySerializer


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})

    def validate(self, attrs):
        user = authenticate(self.context["request"], username=attrs["username"], password=attrs["password"])
        # Platform operators sign in only through the platform login.
        if user is None or not user.is_active or user.is_platform_operator:
            # One message for both cases so usernames cannot be enumerated.
            raise serializers.ValidationError("Invalid username or password.", code="invalid_credentials")
        attrs["user"] = user
        return attrs


class TokenPairSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()


class TokenResultSerializer(serializers.Serializer):
    result = TokenPairSerializer()


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class OrganizationBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MeSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()
    can_change_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "phone_number",
            "email",
            "memberships",
            "organizations",
            "can_change_password",
        ]

    def get_can_change_password(self, obj) -> bool:
        from apps.saas.entitlements import owner_may_change_password

        return owner_may_change_password(obj)

    def get_memberships(self, obj) -> list[dict]:
        memberships = (
            Membership.objects.filter(
                user=obj, is_active=True, clinic__is_active=True, clinic__organization__is_active=True
            )
            .select_related("clinic")
            .order_by("clinic__name")
        )
        return MembershipSummarySerializer(memberships, many=True).data

    def get_organizations(self, obj) -> list[dict]:
        return OrganizationBriefSerializer(obj.owned_organizations.filter(is_active=True), many=True).data


class MeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "phone_number", "email"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.", code="password_incorrect")
        return value

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password

        validate_password(value, self.context["request"].user)
        return value
