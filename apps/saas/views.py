import secrets
import uuid
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.serializers import RefreshSerializer, TokenResultSerializer
from apps.accounts.sessions import revoke_all_sessions
from apps.accounts.throttles import LoginUsernameThrottle
from apps.audit.models import AuditLog
from apps.core.exceptions import BaseUnauthorizedException
from apps.dental.models import Procedure
from apps.imaging.models import Attachment
from apps.patients.models import Patient
from apps.saas import entitlements
from apps.saas.audit import record
from apps.saas.models import Contract, PlatformEvent, PlatformPayment
from apps.saas.permissions import IsPlatformOperator
from apps.saas.serializers import (
    ClinicBriefSerializer,
    DashboardSerializer,
    OperatorSerializer,
    OrganizationCreatedSerializer,
    OrganizationCreateSerializer,
    OrganizationDetailSerializer,
    OrganizationListSerializer,
    OrganizationUpdateSerializer,
    PlatformLoginSerializer,
    PlatformPaymentSerializer,
    PlatformVoidSerializer,
    ResetOwnerPasswordSerializer,
    TemporaryPasswordSerializer,
    UsageSerializer,
    billing_status,
)
from apps.saas.tokens import is_platform_token, platform_refresh_for
from apps.scheduling.models import Appointment
from apps.tenancy.models import Clinic, Membership, Organization
from apps.tenancy.services import ensure_owner_membership
from apps.voice.models import VoiceUsage

Event = PlatformEvent.Action
TAGS = ["Platform"]


def _token_result(refresh: RefreshToken) -> dict:
    return {"result": {"access_token": str(refresh.access_token), "refresh_token": str(refresh)}}


def _temporary_password() -> str:
    return secrets.token_urlsafe(9)


def _month_start():
    return timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class PlatformLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "login"
    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]

    @extend_schema(request=PlatformLoginSerializer, responses={200: TokenResultSerializer}, tags=TAGS)
    def post(self, request):
        params = PlatformLoginSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        user = authenticate(
            request, username=params.validated_data["username"], password=params.validated_data["password"]
        )
        if user is None or not user.is_active or not user.is_platform_operator:
            # Same answer as a wrong password: clinic logins must not learn this door exists.
            raise ValidationError({"non_field_errors": ["Invalid username or password."]}, code="invalid_credentials")
        request.user = user
        record(request, Event.LOGIN)
        return Response(_token_result(platform_refresh_for(user)))


class PlatformRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "login"

    @extend_schema(request=RefreshSerializer, responses={200: TokenResultSerializer}, tags=TAGS)
    def post(self, request):
        params = RefreshSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        expired = BaseUnauthorizedException(message="Session expired.", message_key="session_expired")
        try:
            old = RefreshToken(params.validated_data["refresh_token"])
            if not is_platform_token(old):
                raise expired
            user_id = old["user_id"]
            old.blacklist()
        except TokenError as err:
            raise expired from err
        user = User.objects.filter(pk=user_id, is_active=True, is_platform_operator=True).first()
        if user is None:
            raise expired
        return Response(_token_result(platform_refresh_for(user)))


class PlatformLogoutView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(request=RefreshSerializer, responses={204: None}, tags=TAGS)
    def post(self, request):
        params = RefreshSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        try:
            token = RefreshToken(params.validated_data["refresh_token"])
            if str(token["user_id"]) == str(request.user.pk):
                token.blacklist()
        except TokenError:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlatformMeView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(responses={200: OperatorSerializer}, tags=TAGS)
    def get(self, request):
        return Response(OperatorSerializer(request.user).data)


@extend_schema(tags=TAGS)
class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Customers. There is no delete: suspending blocks every login and keeps the medical records."""

    permission_classes = [IsPlatformOperator]
    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = Organization.objects.prefetch_related("clinics", "owners").order_by("name")

    def get_serializer_class(self):
        return OrganizationListSerializer if self.action == "list" else OrganizationDetailSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "today": timezone.localdate()}

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Part of the customer's business name."),
            OpenApiParameter("is_active", bool),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action != "list":
            return queryset
        # Business names, not patient data, so a query parameter is fine here.
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        is_active = self.request.query_params.get("is_active")
        if is_active in ("true", "false"):
            queryset = queryset.filter(is_active=is_active == "true")
        return queryset

    def _detail(self, organization):
        organization = self.get_queryset().get(pk=organization.pk)
        return OrganizationDetailSerializer(organization, context=self.get_serializer_context()).data

    @extend_schema(request=OrganizationCreateSerializer, responses={201: OrganizationCreatedSerializer})
    def create(self, request, *args, **kwargs):
        params = OrganizationCreateSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        password = _temporary_password()
        with transaction.atomic():
            organization = Organization.objects.create(name=data["name"])
            Contract.objects.create(organization=organization, **data.get("contract", {}))
            owner = User.objects.create_user(password=password, **data["owner"])
            organization.owners.add(owner)
            clinic = Clinic.objects.create(organization=organization, **data["clinic"])
            ensure_owner_membership(clinic, owner)
            record(request, Event.CREATE, organization, organization)
        body = {
            "organization": self._detail(organization),
            "owner_username": owner.username,
            "owner_temporary_password": password,
        }
        # `organization` is already serialized; the response serializer documents the shape.
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=OrganizationUpdateSerializer, responses={200: OrganizationDetailSerializer})
    def partial_update(self, request, *args, **kwargs):
        organization = self.get_object()
        params = OrganizationUpdateSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        with transaction.atomic():
            if "name" in params.validated_data:
                organization.name = params.validated_data["name"]
                organization.save(update_fields=["name", "updated_at"])
            changes = params.validated_data.get("contract")
            if changes:
                contract, _ = Contract.objects.get_or_create(organization=organization)
                for field, value in changes.items():
                    setattr(contract, field, value)
                contract.save()
            record(request, Event.UPDATE, organization, organization)
        return Response(self._detail(organization))

    def _set_active(self, request, active: bool):
        organization = self.get_object()
        organization.is_active = active
        organization.save(update_fields=["is_active", "updated_at"])
        record(request, Event.REACTIVATE if active else Event.SUSPEND, organization, organization)
        return Response(self._detail(organization))

    @extend_schema(request=None, responses={200: OrganizationDetailSerializer})
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._set_active(request, False)

    @extend_schema(request=None, responses={200: OrganizationDetailSerializer})
    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._set_active(request, True)

    @extend_schema(request=ClinicBriefSerializer, responses={201: OrganizationDetailSerializer})
    @action(detail=True, methods=["post"], url_path="clinics")
    def add_clinic(self, request, pk=None):
        organization = self.get_object()
        params = ClinicBriefSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        with transaction.atomic():
            clinic = Clinic.objects.create(organization=organization, **params.validated_data)
            for owner in organization.owners.all():
                ensure_owner_membership(clinic, owner)
            record(request, Event.CREATE, organization, clinic)
        return Response(self._detail(organization), status=status.HTTP_201_CREATED)

    @extend_schema(request=ResetOwnerPasswordSerializer, responses={200: TemporaryPasswordSerializer})
    @action(detail=True, methods=["post"], url_path="reset-owner-password")
    def reset_owner_password(self, request, pk=None):
        organization = self.get_object()
        params = ResetOwnerPasswordSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        owner = organization.owners.filter(pk=params.validated_data["owner"]).first()
        if owner is None:
            raise ValidationError({"owner": "Not an owner of this organization."}, code="invalid")
        password = _temporary_password()
        owner.set_password(password)
        owner.save(update_fields=["password", "updated_at"])
        revoke_all_sessions(owner)
        record(request, Event.RESET_PASSWORD, organization, owner)
        return Response(TemporaryPasswordSerializer({"username": owner.username, "temporary_password": password}).data)

    @extend_schema(responses={200: UsageSerializer})
    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        organization = self.get_object()
        clinics = organization.clinics.all()
        month = _month_start()
        files = Attachment.objects.filter(clinic__in=clinics).aggregate(count=Count("id"), size=Sum("size_bytes"))
        staff_ids = Membership.objects.filter(clinic__in=clinics, is_active=True).values("user_id")
        last_login = (
            AuditLog.objects.filter(action=AuditLog.Action.LOGIN, actor__in=staff_ids).order_by("-created_at").first()
        )
        body = {
            "clinics": clinics.count(),
            "active_clinics": clinics.filter(is_active=True).count(),
            "staff": staff_ids.distinct().count(),
            "patients": Patient.objects.filter(clinic__in=clinics).count(),
            "appointments_this_month": Appointment.objects.filter(clinic__in=clinics, start_at__gte=month).count(),
            "procedures_this_month": Procedure.objects.filter(clinic__in=clinics, performed_at__gte=month).count(),
            "voice_drafts_this_month": VoiceUsage.objects.filter(clinic__in=clinics, created_at__gte=month).count(),
            "voice_monthly_limit": entitlements.voice_limit(organization),
            "attachments": files["count"],
            "attachments_bytes": files["size"] or 0,
            "last_login_at": last_login.created_at if last_login else None,
        }
        return Response(UsageSerializer(body).data)


@extend_schema(tags=TAGS)
class PlatformClinicViewSet(viewsets.GenericViewSet):
    """One branch of a customer: suspend or bring back without touching the others."""

    permission_classes = [IsPlatformOperator]
    queryset = Clinic.objects.select_related("organization")
    serializer_class = ClinicBriefSerializer

    def _set_active(self, request, active: bool):
        clinic = self.get_object()
        clinic.is_active = active
        clinic.save(update_fields=["is_active", "updated_at"])
        record(request, Event.REACTIVATE if active else Event.SUSPEND, clinic.organization, clinic)
        return Response(ClinicBriefSerializer(clinic).data)

    @extend_schema(request=None, responses={200: ClinicBriefSerializer})
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._set_active(request, False)

    @extend_schema(request=None, responses={200: ClinicBriefSerializer})
    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._set_active(request, True)


@extend_schema(tags=TAGS)
class PlatformPaymentViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """What customers paid the vendor. Never edited or deleted; a mistake is voided with a reason."""

    permission_classes = [IsPlatformOperator]
    queryset = PlatformPayment.objects.select_related("recorded_by")
    serializer_class = PlatformPaymentSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("organization", str, description="Organization id."),
            OpenApiParameter("kind", str, enum=PlatformPayment.Kind.values),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if params.get("organization"):
            try:
                organization_id = uuid.UUID(params["organization"])
            except ValueError as err:
                raise ValidationError({"organization": "Must be a UUID."}, code="invalid") from err
            queryset = queryset.filter(organization_id=organization_id)
        if params.get("kind"):
            queryset = queryset.filter(kind=params["kind"])
        return queryset

    def perform_create(self, serializer):
        payment = serializer.save(recorded_by=self.request.user)
        record(self.request, Event.PAYMENT, payment.organization, payment)

    @extend_schema(request=PlatformVoidSerializer, responses={200: PlatformPaymentSerializer})
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        payment = self.get_object()
        params = PlatformVoidSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        if payment.voided_at is not None:
            raise ValidationError({"payment": "Already voided."}, code="already_voided")
        payment.voided_at = timezone.now()
        payment.voided_by = request.user
        payment.void_reason = params.validated_data["reason"]
        payment.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
        record(request, Event.VOID, payment.organization, payment)
        return Response(PlatformPaymentSerializer(payment).data)


class DashboardView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(responses={200: DashboardSerializer}, tags=TAGS)
    def get(self, request):
        today = timezone.localdate()
        live = PlatformPayment.objects.filter(voided_at__isnull=True)

        def collected(since):
            return list(
                live.filter(paid_on__gte=since)
                .values("currency", "kind")
                .annotate(total=Sum("amount"))
                .order_by("currency", "kind")
            )

        overdue, expiring, install_due = [], [], []
        organizations = Organization.objects.filter(is_active=True).order_by("name")
        for organization in organizations:
            billing = billing_status(organization, today)
            brief = {
                "id": organization.pk,
                "name": organization.name,
                "server_paid_until": billing["server_paid_until"],
            }
            if billing["server_overdue"]:
                overdue.append(brief)
            elif billing["server_paid_until"] and billing["server_paid_until"] <= today + timedelta(days=30):
                expiring.append(brief)
            if billing["install_due"] > 0:
                install_due.append(
                    {
                        "id": organization.pk,
                        "name": organization.name,
                        "currency": billing["currency"],
                        "due": billing["install_due"],
                    }
                )
        body = {
            "organizations": Organization.objects.count(),
            "active_organizations": organizations.count(),
            "clinics": Clinic.objects.count(),
            "collected_this_month": collected(today.replace(day=1)),
            "collected_this_year": collected(today.replace(month=1, day=1)),
            "server_overdue": overdue,
            "server_expiring": expiring,
            "install_due": install_due,
        }
        return Response(DashboardSerializer(body).data)
