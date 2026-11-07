from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.bot.credentials import reveal
from apps.bot.models import BotAccount
from apps.bot.serializers import BotAccessSerializer
from apps.tenancy.models import Membership
from apps.tenancy.viewsets import ClinicScopedMixin


def respond_with_access(request, account: BotAccount, *, clinic) -> Response:
    """Every read-back of a password is audited: it is a login to someone's records."""
    record(request, AuditLog.Action.VIEW, account, clinic=clinic)
    return Response(BotAccessSerializer(reveal(account)).data)


class MyBotAccessViewSet(ClinicScopedMixin, viewsets.GenericViewSet):
    """The caller's own bot login. Only doctors and owners have one."""

    queryset = Membership.objects.none()
    serializer_class = BotAccessSerializer
    required_permissions = {"bot_access": "clinic:view"}

    def get_queryset(self):
        return self.queryset

    @extend_schema(responses={200: BotAccessSerializer})
    @action(detail=False, methods=["get"], url_path="bot-access")
    def bot_access(self, request):
        account = BotAccount.objects.filter(user=request.user).first()
        if account is None:
            raise NotFound()
        return respond_with_access(request, account, clinic=request.clinic)
