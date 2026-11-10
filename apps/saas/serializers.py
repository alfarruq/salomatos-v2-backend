from rest_framework import serializers

from apps.accounts.models import User
from apps.core.validators import validate_phone
from apps.saas import entitlements
from apps.saas.models import Contract, PlatformPayment
from apps.tenancy.models import Clinic, Organization

Kind = PlatformPayment.Kind


class PlatformLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})


class OperatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "full_name"]


class ContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = [
            "currency",
            "install_fee",
            "server_fee_yearly",
            "voice_fee_monthly",
            "voice_enabled",
            "voice_monthly_limit",
            "signed_on",
            "note",
        ]


class ClinicBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = ["id", "name", "phone_number", "address", "is_active", "created_at"]
        read_only_fields = ["id", "is_active", "created_at"]


class OwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "full_name", "phone_number", "is_active"]
        read_only_fields = ["id", "is_active"]


class BillingStatusSerializer(serializers.Serializer):
    currency = serializers.CharField()
    install_fee = serializers.DecimalField(max_digits=14, decimal_places=2)
    install_paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    install_due = serializers.DecimalField(max_digits=14, decimal_places=2)
    server_paid_until = serializers.DateField(allow_null=True)
    server_overdue = serializers.BooleanField()
    voice_paid_until = serializers.DateField(allow_null=True)
    voice_active = serializers.BooleanField()
    sms_credits = serializers.IntegerField()


def billing_status(organization, today) -> dict:
    contract = entitlements.contract_of(organization) or Contract(organization=organization)
    install_paid = entitlements.paid_total(organization, Kind.INSTALL)
    server_until = entitlements.paid_until(organization, Kind.SERVER)
    return {
        "currency": contract.currency,
        "install_fee": contract.install_fee,
        "install_paid": install_paid,
        "install_due": max(contract.install_fee - install_paid, 0),
        "server_paid_until": server_until,
        # A customer with no server fee agreed owes nothing for the server.
        "server_overdue": contract.server_fee_yearly > 0 and (server_until is None or server_until < today),
        "voice_paid_until": entitlements.paid_until(organization, Kind.VOICE),
        "voice_active": entitlements.voice_active(organization, today),
        "sms_credits": entitlements.sms_credits(organization),
    }


class OrganizationListSerializer(serializers.ModelSerializer):
    clinic_count = serializers.SerializerMethodField()
    billing = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "is_active", "created_at", "clinic_count", "billing"]

    def get_clinic_count(self, obj) -> int:
        return obj.clinics.count()

    @staticmethod
    def _today(serializer):
        return serializer.context["today"]

    def get_billing(self, obj) -> BillingStatusSerializer:
        return BillingStatusSerializer(billing_status(obj, self._today(self))).data


class OrganizationDetailSerializer(OrganizationListSerializer):
    contract = serializers.SerializerMethodField()
    clinics = ClinicBriefSerializer(many=True, read_only=True)
    owners = OwnerSerializer(many=True, read_only=True)

    class Meta(OrganizationListSerializer.Meta):
        fields = [*OrganizationListSerializer.Meta.fields, "contract", "clinics", "owners"]

    def get_contract(self, obj) -> ContractSerializer:
        contract = entitlements.contract_of(obj) or Contract(organization=obj)
        return ContractSerializer(contract).data


class NewOwnerSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    full_name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=16, required=False, allow_blank=True, validators=[validate_phone])

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is taken.", code="duplicate")
        return value


class OrganizationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    contract = ContractSerializer(required=False)
    clinic = ClinicBriefSerializer()
    owner = NewOwnerSerializer()


class OrganizationUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    contract = ContractSerializer(required=False, partial=True)


class OrganizationCreatedSerializer(serializers.Serializer):
    organization = OrganizationDetailSerializer()
    owner_username = serializers.CharField()
    # Shown once so the vendor can hand it over; the owner changes it after the first login.
    owner_temporary_password = serializers.CharField()


class ResetOwnerPasswordSerializer(serializers.Serializer):
    owner = serializers.UUIDField()


class TemporaryPasswordSerializer(serializers.Serializer):
    username = serializers.CharField()
    temporary_password = serializers.CharField()


class UsageSerializer(serializers.Serializer):
    """Counts only. The vendor sizes and bills the customer; it never sees whose records they are."""

    clinics = serializers.IntegerField()
    active_clinics = serializers.IntegerField()
    staff = serializers.IntegerField()
    patients = serializers.IntegerField()
    appointments_this_month = serializers.IntegerField()
    procedures_this_month = serializers.IntegerField()
    voice_drafts_this_month = serializers.IntegerField()
    voice_monthly_limit = serializers.IntegerField()
    attachments = serializers.IntegerField()
    attachments_bytes = serializers.IntegerField()
    last_login_at = serializers.DateTimeField(allow_null=True)


class PlatformPaymentSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all())
    currency = serializers.ChoiceField(choices=Contract._meta.get_field("currency").choices, required=False)
    recorded_by = OperatorSerializer(read_only=True)

    class Meta:
        model = PlatformPayment
        fields = [
            "id",
            "organization",
            "kind",
            "amount",
            "currency",
            "method",
            "paid_on",
            "covers_until",
            "sms_credits",
            "note",
            "recorded_by",
            "created_at",
            "voided_at",
            "void_reason",
        ]
        read_only_fields = ["id", "recorded_by", "created_at", "voided_at", "void_reason"]

    def validate(self, attrs):
        kind = attrs["kind"]
        if kind in (Kind.SERVER, Kind.VOICE):
            if attrs.get("covers_until") is None:
                raise serializers.ValidationError({"covers_until": "Required for this kind."}, code="required")
            if attrs["covers_until"] < attrs["paid_on"]:
                raise serializers.ValidationError({"covers_until": "Must not be before paid_on."}, code="invalid")
        else:
            attrs["covers_until"] = None
        if kind == Kind.SMS:
            if not attrs.get("sms_credits"):
                raise serializers.ValidationError({"sms_credits": "Required for SMS."}, code="required")
        else:
            attrs["sms_credits"] = None
        if not attrs.get("currency"):
            contract = entitlements.contract_of(attrs["organization"])
            attrs["currency"] = contract.currency if contract else Contract._meta.get_field("currency").default
        return attrs


class PlatformVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AmountByCurrencySerializer(serializers.Serializer):
    currency = serializers.CharField()
    kind = serializers.CharField()
    total = serializers.DecimalField(max_digits=16, decimal_places=2)


class OrganizationBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    server_paid_until = serializers.DateField(allow_null=True)


class InstallDueSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    currency = serializers.CharField()
    due = serializers.DecimalField(max_digits=14, decimal_places=2)


class DashboardSerializer(serializers.Serializer):
    organizations = serializers.IntegerField()
    active_organizations = serializers.IntegerField()
    clinics = serializers.IntegerField()
    collected_this_month = AmountByCurrencySerializer(many=True)
    collected_this_year = AmountByCurrencySerializer(many=True)
    server_overdue = OrganizationBriefSerializer(many=True)
    server_expiring = OrganizationBriefSerializer(many=True)
    install_due = InstallDueSerializer(many=True)
