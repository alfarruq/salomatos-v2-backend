from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, JsonResponse
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException, ErrorDetail, MethodNotAllowed
from rest_framework.response import Response
from rest_framework.views import exception_handler


class BaseAPIException(APIException):
    default_message = "Error"
    default_message_key = "error"
    default_errors = {}

    def __init__(
        self,
        detail=None,
        code=None,
        message=None,
        message_key=None,
        errors=None,
    ):
        super().__init__(detail, code)
        self.message = message or self.default_message
        self.message_key = message_key or self.default_message_key
        self.errors = errors or self.default_errors


class APIExceptionFormatter:
    def __init__(self, exception: APIException):
        self.exception_class = exception.__class__.__name__
        self.detail = exception.detail
        self.default_code = exception.default_code
        self.message = getattr(exception, "message", None) or exception.default_detail
        self.message_key = getattr(exception, "message_key", None) or self.default_code
        self.errors = getattr(exception, "errors", None) or (self.detail if isinstance(self.detail, dict) else {})
        if isinstance(self.detail, dict):
            for key, value in self.detail.items():
                if isinstance(value, list | tuple):
                    value = value[0]
                    self.detail[key] = value.code if isinstance(value, ErrorDetail) else str(value)
                elif isinstance(value, dict):
                    self.detail[key] = value
                else:
                    self.detail[key] = str(value)

        if isinstance(exception, MethodNotAllowed):
            self.message = self.detail
            self.message_key = self.default_code
            self.errors = {}

    def get_response(self):
        return {
            "message": self.message,
            "message_key": self.message_key,
            "errors": self.errors,
            "exception_class": self.exception_class,
        }


def server_error(request, *args, **kwargs):
    # The exception text can carry PHI (a model's __str__, a query value), so
    # the client only ever gets a generic message; details stay in server logs.
    data = {
        "message": "Internal server error",
        "message_key": "internal_server_error",
        "errors": {},
        "exception_class": "ServerError",
    }
    return JsonResponse(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def drf_exception_handler(exception, context):
    response = exception_handler(exception, context)
    if isinstance(exception, Http404 | ObjectDoesNotExist):
        return Response(
            {
                "message": "Not found",
                "message_key": "not_found",
                "errors": {},
                "exception_class": "NotFound",
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    if response is not None:
        formatted_exception = APIExceptionFormatter(exception)
        response.data = formatted_exception.get_response()
    return response


class TryAgainException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Try again")
    default_message_key = "try_again"


class BaseUnauthorizedException(BaseAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = _("Unauthorized")
    default_message_key = "unauthorized"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ValidationError(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Validation error")
    default_message_key = "validation_error"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ExternalServiceException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "External Service error"
    default_message_key = "external_service_error"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ActionNotAllowedException(BaseAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_message = _("Action not allowed")
    default_message_key = "action_not_allowed"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ObjectAlreadyExistsException(BaseAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_message = _("The object already exists")
    default_message_key = "object_already_exists"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ObjectNotFoundException(BaseAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_message = _("Object not found")
    default_message_key = "object_not_found"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class UserAlreadyExistsException(BaseAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_message = _("The user already exists")
    default_message_key = "user_already_exists"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class InvalidAuthCredentialsException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Invalid authentication credentials")
    default_message_key = "invalid_credentials"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class MissingFieldException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("This field is missing")
    default_message_key = "this_field_is_missing"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ObjectIsNotAvailableException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("The object is not available")
    default_message_key = "object_is_not_available"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class MissingParamsException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Missing params")
    default_message_key = "missing_params"


class OldPasswordRequiredException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Old password required")
    default_message_key = "old_password_required"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class PasswordIncorrectException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Incorrect old password")
    default_message_key = "incorrect_old_password"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class NewPasswordRequiredException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("New password required")
    default_message_key = "new_password_required"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class PasswordsDontMatchException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Passwords do not match")
    default_message_key = "passwords_do_not_match"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class PermissionDeniedException(BaseAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_message = _("Permission denied")
    default_message_key = "permission_denied"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
