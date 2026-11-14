from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.tenancy.fields import ClinicRelatedField
from apps.tenancy.models import Clinic, Membership, Specialty
from apps.tenancy.permissions import permissions_for

User = get_user_model()


def _this_month(clinic: Clinic) -> date:
    return timezone.now().astimezone(ZoneInfo(clinic.timezone)).date().replace(day=1)


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
        fields = ["id", "name", "is_dental"]
        read_only_fields = ["is_dental"]

    def validate_name(self, value):
        if self.instance is not None and self.instance.is_dental:
            raise serializers.ValidationError("The dental specialty cannot be renamed.", code="protected")
        clinic = self.context["request"].clinic
        qs = Specialty.objects.filter(clinic=clinic, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A specialty with this name already exists.", code="duplicate")
        return value


class PayTermsSerializer(serializers.Serializer):
    """A doctor's pay at hiring: a monthly salary, a percent of their work, or both."""

    percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"), default=Decimal("0")
    )
    fixed = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), default=Decimal("0"))
    base = serializers.ChoiceField(choices=["collected", "billed"], default="collected")
    effective_from = serializers.CharField(read_only=True, help_text="YYYY-MM")

    def to_representation(self, instance):
        return {
            "percent": f"{instance.percent:.2f}",
            "fixed": f"{instance.fixed:.2f}",
            "base": instance.base,
            "effective_from": instance.effective_from.strftime("%Y-%m"),
        }

    def validate(self, attrs):
        # A switched-off half of the form is simply absent, and a partial update skips defaults.
        attrs.setdefault("percent", Decimal("0"))
        attrs.setdefault("fixed", Decimal("0"))
        attrs.setdefault("base", "collected")
        if attrs["percent"] == 0 and attrs["fixed"] == 0:
            raise serializers.ValidationError({"percent": "Give a percent, a salary, or both."}, code="required")
        return attrs


class StaffSerializer(serializers.ModelSerializer):
    """A clinic employee: the membership plus the login it belongs to."""

    username = serializers.CharField(source="user.username")
    full_name = serializers.CharField(source="user.full_name")
    phone_number = serializers.CharField(source="user.phone_number", required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})
    specialty = ClinicRelatedField(queryset=Specialty.objects.all(), required=False, allow_null=True)
    specialty_name = serializers.CharField(source="specialty.name", read_only=True, default=None)
    specialty_is_dental = serializers.BooleanField(source="specialty.is_dental", read_only=True, default=False)
    compensation = PayTermsSerializer(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="A new doctor's pay terms, from this month. Create only; owners only (payroll:manage).",
    )
    current_compensation = serializers.SerializerMethodField(
        help_text="The doctor's pay terms this month. Sent only to callers with payroll:view."
    )

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
            "specialty_is_dental",
            "experience_years",
            "biography",
            "compensation",
            "current_compensation",
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
        if attrs.get("compensation") is not None:
            if self.instance is not None:
                # Later changes are new rows through /compensations/, so paid months keep their terms.
                raise serializers.ValidationError(
                    {"compensation": "Change pay terms through compensations."}, code="invalid"
                )
            if attrs.get("role") != Membership.Role.DOCTOR:
                raise serializers.ValidationError({"compensation": "Only a doctor has pay terms."}, code="invalid")
            if "payroll:manage" not in permissions_for(self.context["request"].membership):
                raise serializers.ValidationError({"compensation": "Only an owner sets pay terms."}, code="forbidden")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from apps.finance.models import Compensation

        user_data = validated_data.pop("user")
        password = validated_data.pop("password")
        terms = validated_data.pop("compensation", None)
        user = User.objects.create_user(password=password, **user_data)
        membership = Membership.objects.create(user=user, **validated_data)
        if terms is not None:
            request = self.context["request"]
            Compensation.objects.create(
                clinic=membership.clinic,
                doctor=membership,
                created_by=request.membership,
                effective_from=_this_month(membership.clinic),
                **terms,
            )
        return membership

    def _sees_pay(self) -> bool:
        request = self.context.get("request")
        return request is not None and "payroll:view" in permissions_for(request.membership)

    @extend_schema_field(PayTermsSerializer(allow_null=True))
    def get_current_compensation(self, instance):
        if instance.role != Membership.Role.DOCTOR or not self._sees_pay():
            return None
        month = _this_month(instance.clinic)
        # Newest first (Compensation.Meta.ordering); prefetched by the staff list.
        terms = next((row for row in instance.compensations.all() if row.effective_from <= month), None)
        return None if terms is None else PayTermsSerializer(terms).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._sees_pay():
            # Pay is the owner's business: nobody else even learns the field exists.
            data.pop("current_compensation", None)
        return data

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
