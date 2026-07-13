import pytest
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.responses import error_response, success_response


def test_success_response_shape():
    response = success_response({"id": 1})

    assert response.data == {
        "success": True,
        "code": ErrorCode.OK,
        "message": "success",
        "data": {"id": 1},
    }


def test_error_response_shape():
    response = error_response(ErrorCode.TENANT_REQUIRED, "tenant is required")

    assert response.data == {
        "success": False,
        "code": ErrorCode.TENANT_REQUIRED,
        "message": "tenant is required",
        "data": None,
    }


def test_error_codes_exist():
    assert ErrorCode.AUTH_REQUIRED == "AUTH_REQUIRED"
    assert ErrorCode.PERMISSION_DENIED == "PERMISSION_DENIED"
    assert ErrorCode.TENANT_REQUIRED == "TENANT_REQUIRED"
    assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
    assert ErrorCode.BUSINESS_RULE_VIOLATION == "BUSINESS_RULE_VIOLATION"
    assert ErrorCode.STATE_CONFLICT == "STATE_CONFLICT"
    assert ErrorCode.NOT_FOUND == "NOT_FOUND"
    assert ErrorCode.RPA_AGENT_INVALID == "RPA_AGENT_INVALID"
    assert ErrorCode.API_SYNC_FAILED == "API_SYNC_FAILED"
    assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"


@pytest.mark.django_db
def test_drf_not_authenticated_exception_uses_unified_format():
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def protected_view(request):
        return success_response()

    request = APIRequestFactory().get("/protected/")
    response = protected_view(request)

    assert response.status_code == 401
    assert response.data["success"] is False
    assert response.data["code"] == ErrorCode.AUTH_REQUIRED
    assert response.data["data"] is None


def test_drf_validation_exception_uses_unified_format():
    class ExampleSerializer(serializers.Serializer):
        name = serializers.CharField(required=True)

    class ExampleView(APIView):
        def post(self, request):
            serializer = ExampleSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return success_response(serializer.validated_data)

    request = APIRequestFactory().post("/example/", {}, format="json")
    response = ExampleView.as_view()(request)

    assert response.status_code == 400
    assert response.data["success"] is False
    assert response.data["code"] == ErrorCode.VALIDATION_ERROR
    assert response.data["message"] == "error message"
    assert "name" in response.data["data"]


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (PermissionDenied("denied"), 403, ErrorCode.PERMISSION_DENIED),
        (NotFound("missing"), 404, ErrorCode.NOT_FOUND),
        (StateConflict("already handled"), 409, ErrorCode.STATE_CONFLICT),
        (BusinessRuleViolation("rule failed"), 422, ErrorCode.BUSINESS_RULE_VIOLATION),
    ],
)
def test_contract_error_statuses_use_the_unified_envelope(exception, expected_status, expected_code):
    class ExampleView(APIView):
        def get(self, request):
            raise exception

    response = ExampleView.as_view()(APIRequestFactory().get("/example/"))

    assert response.status_code == expected_status
    assert response.data["success"] is False
    assert response.data["code"] == expected_code
    assert response.data["data"] is None
