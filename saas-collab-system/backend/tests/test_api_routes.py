import pytest
from rest_framework.test import APIClient

from apps.permissions.api_permissions import IsExternalUser, IsFinanceUser, IsInternalUser, IsRPAAgent


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "service"),
    [
        ("/api/internal/health/", "internal"),
        ("/api/external/health/", "external"),
        ("/api/rpa/health/", "rpa"),
        ("/api/platform/health/", "platform"),
        ("/api/report/health/", "report"),
    ],
)
def test_health_routes(path, service):
    response = APIClient().get(path)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {"status": "ok", "service": service},
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "service"),
    [
        ("/api/wechat/health/", "wechat"),
        ("/api/feishu/health/", "feishu"),
    ],
)
def test_callback_partition_health_routes(path, service):
    response = APIClient().get(path)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {"status": "ok", "service": service},
    }


@pytest.mark.django_db
def test_unauthorized_failure_response_uses_standard_shape():
    response = APIClient().get("/api/internal/auth/me/")

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "code": "AUTH_REQUIRED",
        "message": "Authentication credentials were not provided.",
        "data": None,
    }


def test_permission_placeholders_exist():
    assert IsInternalUser is not None
    assert IsExternalUser is not None
    assert IsRPAAgent is not None
    assert IsFinanceUser is not None
