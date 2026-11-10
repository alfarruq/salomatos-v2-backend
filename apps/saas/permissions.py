from rest_framework.permissions import BasePermission

from apps.saas.tokens import is_platform_token


class IsPlatformOperator(BasePermission):
    """The vendor's own staff, signed in through the platform login.

    Operators hold no clinic membership, so this side never reaches patient
    data; it reads organizations, contracts, payments and counts only.
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active and user.is_platform_operator
        ) and is_platform_token(request.auth)
