from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    MeSerializer,
    MeUpdateSerializer,
    RefreshSerializer,
    TokenResultSerializer,
)
from apps.accounts.sessions import revoke_all_sessions
from apps.accounts.throttles import LoginUsernameThrottle
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.core.exceptions import BaseUnauthorizedException
from apps.saas import entitlements


def _token_result(refresh: RefreshToken) -> dict:
    # Wrapped in `result` because the frontend already reads that shape.
    return {"result": {"access_token": str(refresh.access_token), "refresh_token": str(refresh)}}


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "login"
    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]

    @extend_schema(request=LoginSerializer, responses={200: TokenResultSerializer}, tags=["Auth"])
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        request.user = user
        record(request, AuditLog.Action.LOGIN, user, clinic=None)
        return Response(_token_result(RefreshToken.for_user(user)))


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "login"

    @extend_schema(request=RefreshSerializer, responses={200: TokenResultSerializer}, tags=["Auth"])
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            old = RefreshToken(serializer.validated_data["refresh_token"])
            user_id = old["user_id"]
            old.blacklist()
        except TokenError as err:
            raise BaseUnauthorizedException(message="Session expired.", message_key="session_expired") from err
        from apps.accounts.models import User

        user = User.objects.filter(pk=user_id, is_active=True, is_platform_operator=False).first()
        if user is None:
            raise BaseUnauthorizedException(message="Session expired.", message_key="session_expired")
        return Response(_token_result(RefreshToken.for_user(user)))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=RefreshSerializer, responses={204: None}, tags=["Auth"])
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh_token"])
            if str(token["user_id"]) == str(request.user.pk):
                token.blacklist()
        except TokenError:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MeSerializer}, tags=["Auth"])
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    @extend_schema(request=MeUpdateSerializer, responses={200: MeSerializer}, tags=["Auth"])
    def patch(self, request):
        serializer = MeUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ChangePasswordSerializer, responses={204: None}, tags=["Auth"])
    def post(self, request):
        if not entitlements.owner_may_change_password(request.user):
            raise PermissionDenied("Your password is managed by the vendor. Ask them to change it.", "password_managed")
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password", "updated_at"])
        revoke_all_sessions(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
