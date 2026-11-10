import logging

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, Throttled
from rest_framework.response import Response

from apps.patients.access import ensure_patient_visible
from apps.saas import entitlements
from apps.saas.models import PlatformPayment
from apps.tenancy.viewsets import ClinicScopedMixin
from apps.voice import llm
from apps.voice.drafts import FORMS, build_draft
from apps.voice.models import VoiceUsage
from apps.voice.serializers import VoiceDraftRequestSerializer, VoiceDraftSerializer, VoiceStatusSerializer

logger = logging.getLogger(__name__)


class VoiceUnavailableError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Voice input is not configured."
    default_code = "voice_unavailable"


class VoiceNotSubscribedError(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "The voice add-on is not paid for this clinic."
    default_code = "voice_not_subscribed"


class VoiceFailedError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Could not read the dictation. Try again or fill the form by hand."
    default_code = "voice_failed"


def _used_this_month(clinic) -> int:
    start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return VoiceUsage.objects.filter(clinic=clinic, created_at__gte=start).count()


class VoiceViewSet(ClinicScopedMixin, viewsets.GenericViewSet):
    """Dictation -> form draft. Writes nothing clinical; the normal endpoints do."""

    queryset = VoiceUsage.objects.none()
    serializer_class = VoiceDraftSerializer
    required_permissions = {"status": "voice:use", "draft": "voice:use"}

    def get_queryset(self):
        return self.queryset

    @extend_schema(responses={200: VoiceStatusSerializer})
    @action(detail=False, methods=["get"])
    def status(self, request):
        organization = request.clinic.organization
        subscribed = entitlements.voice_active(organization)
        return Response(
            VoiceStatusSerializer(
                {
                    "enabled": llm.is_configured() and subscribed,
                    "subscribed": subscribed,
                    "paid_until": entitlements.paid_until(organization, PlatformPayment.Kind.VOICE),
                    "used_this_month": _used_this_month(request.clinic),
                    "monthly_limit": entitlements.voice_limit(organization),
                }
            ).data
        )

    @extend_schema(request=VoiceDraftRequestSerializer, responses={200: VoiceDraftSerializer})
    @action(detail=False, methods=["post"])
    def draft(self, request):
        params = VoiceDraftRequestSerializer(data=request.data, context=self.get_serializer_context())
        params.is_valid(raise_exception=True)
        form = params.validated_data["form"]
        # Voice may only prepare what the caller could submit by hand.
        if not self.has_perm(FORMS[form].permission):
            raise PermissionDenied()
        patient = params.validated_data.get("patient")
        if patient is not None:
            ensure_patient_visible(request, patient)
        organization = request.clinic.organization
        # A paid add-on: the vendor turns it on per customer from the platform panel.
        if not entitlements.voice_active(organization):
            raise VoiceNotSubscribedError()
        if _used_this_month(request.clinic) >= entitlements.voice_limit(organization):
            raise Throttled(detail="The clinic's monthly voice limit is used up.")

        try:
            draft, extraction = build_draft(request, form, params.validated_data["text"], patient)
        except llm.VoiceUnavailable:
            raise VoiceUnavailableError() from None
        except llm.VoiceFailed as error:
            # Reason code only, never the dictation.
            logger.warning("voice draft failed: %s", error)
            raise VoiceFailedError() from None

        VoiceUsage.objects.create(
            clinic=request.clinic,
            member=request.membership,
            form=form,
            input_tokens=extraction.input_tokens,
            output_tokens=extraction.output_tokens,
        )
        return Response(VoiceDraftSerializer(draft).data)
