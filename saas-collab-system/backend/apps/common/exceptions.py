from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.views import exception_handler

from .error_codes import ErrorCode


ERROR_CODE_BY_EXCEPTION = {
    exceptions.AuthenticationFailed: ErrorCode.AUTH_REQUIRED,
    exceptions.NotAuthenticated: ErrorCode.AUTH_REQUIRED,
    exceptions.PermissionDenied: ErrorCode.PERMISSION_DENIED,
    exceptions.ValidationError: ErrorCode.VALIDATION_ERROR,
    exceptions.NotFound: ErrorCode.NOT_FOUND,
    Http404: ErrorCode.NOT_FOUND,
}


def _get_error_code(exc, response):
    for exception_class, code in ERROR_CODE_BY_EXCEPTION.items():
        if isinstance(exc, exception_class):
            return code

    if response is None:
        return ErrorCode.INTERNAL_ERROR

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        return ErrorCode.AUTH_REQUIRED
    if response.status_code == status.HTTP_403_FORBIDDEN:
        return ErrorCode.PERMISSION_DENIED
    if response.status_code == status.HTTP_404_NOT_FOUND:
        return ErrorCode.NOT_FOUND
    if response.status_code == status.HTTP_400_BAD_REQUEST:
        return ErrorCode.VALIDATION_ERROR
    if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.INTERNAL_ERROR


def _get_message(response):
    if isinstance(response.data, dict):
        detail = response.data.get("detail")
        if detail:
            return str(detail)
        return "error message"
    if isinstance(response.data, list):
        return "error message"
    return str(response.data) if response.data else "error message"


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    original_data = response.data
    response.data = {
        "success": False,
        "code": _get_error_code(exc, response),
        "message": _get_message(response),
        "data": original_data if isinstance(exc, exceptions.ValidationError) else None,
    }
    return response
