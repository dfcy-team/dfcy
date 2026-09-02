from rest_framework import exceptions, status

from apps.common.error_codes import ErrorCode


# Controlled uppercase error codes for marketplace OAuth flows. They are stored
# in audit/result fields and surfaced in the unified response message; the
# response envelope ``code`` keeps the project-wide ErrorCode value.
OAUTH_STATE_INVALID = "OAUTH_STATE_INVALID"
OAUTH_STATE_EXPIRED = "OAUTH_STATE_EXPIRED"
OAUTH_STATE_CONSUMED = "OAUTH_STATE_CONSUMED"
OAUTH_SESSION_MISMATCH = "OAUTH_SESSION_MISMATCH"
OAUTH_PLATFORM_MISMATCH = "OAUTH_PLATFORM_MISMATCH"
OAUTH_CALLBACK_REJECTED = "OAUTH_CALLBACK_REJECTED"
OAUTH_STORE_BOUND_CONFLICT = "OAUTH_STORE_BOUND_CONFLICT"
OAUTH_PROVIDER_UNAVAILABLE = "OAUTH_PROVIDER_UNAVAILABLE"
OAUTH_RATE_LIMITED = "OAUTH_RATE_LIMITED"
OAUTH_PROVIDER_ERROR = "OAUTH_PROVIDER_ERROR"
OAUTH_AUTH_REJECTED = "OAUTH_AUTH_REJECTED"
OAUTH_DATABASE_FAILURE = "OAUTH_DATABASE_FAILURE"

OAUTH_ERROR_SPECS = {
    OAUTH_STATE_INVALID: (status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_ERROR),
    OAUTH_STATE_EXPIRED: (status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_ERROR),
    OAUTH_STATE_CONSUMED: (status.HTTP_409_CONFLICT, ErrorCode.STATE_CONFLICT),
    OAUTH_SESSION_MISMATCH: (status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_ERROR),
    OAUTH_PLATFORM_MISMATCH: (status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_ERROR),
    OAUTH_CALLBACK_REJECTED: (status.HTTP_409_CONFLICT, ErrorCode.STATE_CONFLICT),
    OAUTH_STORE_BOUND_CONFLICT: (status.HTTP_409_CONFLICT, ErrorCode.STATE_CONFLICT),
    OAUTH_PROVIDER_UNAVAILABLE: (status.HTTP_502_BAD_GATEWAY, ErrorCode.API_SYNC_FAILED),
    OAUTH_RATE_LIMITED: (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.API_SYNC_FAILED),
    OAUTH_PROVIDER_ERROR: (status.HTTP_502_BAD_GATEWAY, ErrorCode.API_SYNC_FAILED),
    OAUTH_AUTH_REJECTED: (status.HTTP_401_UNAUTHORIZED, ErrorCode.API_SYNC_FAILED),
    OAUTH_DATABASE_FAILURE: (status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.API_SYNC_FAILED),
}


class OAuthFlowError(exceptions.APIException):
    """Marketplace OAuth failure carrying a controlled uppercase error code."""

    def __init__(self, controlled_code, detail=None):
        status_code, error_code = OAUTH_ERROR_SPECS[controlled_code]
        self.status_code = status_code
        self.error_code = error_code
        self.controlled_code = controlled_code
        message = str(detail) if detail else f"OAuth flow rejected: {controlled_code}"
        if controlled_code not in message:
            message = f"{controlled_code}: {message}"
        super().__init__(detail=message, code=error_code)


def raise_oauth_error(controlled_code, detail=None):
    if controlled_code not in OAUTH_ERROR_SPECS:
        controlled_code = OAUTH_CALLBACK_REJECTED
    raise OAuthFlowError(controlled_code, detail)
