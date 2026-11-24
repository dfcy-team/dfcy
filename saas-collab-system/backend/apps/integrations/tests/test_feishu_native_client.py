import json

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.feishu_native_client import FeishuNativeClient


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self, response=None):
        self.response = response or Response({"code": 0, "data": {"ok": True}})
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class FakeIdentity:
    def __init__(self, http):
        self.http = http

    def _tenant_token(self, connection):
        return "test-token"


@pytest.fixture
def client():
    http = FakeHttp()
    return FeishuNativeClient(identity=FakeIdentity(http)), http


def test_definition_instance_and_subscribe_contracts(client):
    api, http = client
    assert api.get_definition(object(), "approval-1") == {"ok": True}
    assert api.get_instance(object(), "instance-1") == {"ok": True}
    assert api.subscribe(object(), "approval-1") == {"ok": True}
    assert [(call[0], call[1]) for call in http.calls] == [
        ("GET", "https://open.feishu.cn/open-apis/approval/v4/approvals/approval-1"),
        ("GET", "https://open.feishu.cn/open-apis/approval/v4/instances/instance-1?user_id_type=open_id"),
        ("POST", "https://open.feishu.cn/open-apis/approval/v4/approvals/approval-1/subscribe"),
    ]
    assert all(c[2]["retry"] is False for c in http.calls)


def test_create_instance_serializes_form_and_keeps_caller_uuid(client):
    api, http = client
    result = api.create_instance(object(), {
        "approval_code": "approval-1", "open_id": "ou_user", "uuid": "stable-uuid",
        "form": [{"id": "reason", "value": "Purchase"}],
    })
    assert result == {"ok": True}
    method, url, kwargs = http.calls[0]
    assert (method, url) == ("POST", "https://open.feishu.cn/open-apis/approval/v4/instances")
    assert kwargs["retry"] is False
    assert kwargs["json_body"]["uuid"] == "stable-uuid"
    assert kwargs["json_body"]["open_id"] == "ou_user"
    assert json.loads(kwargs["json_body"]["form"]) == [{"id": "reason", "value": "Purchase"}]


@pytest.mark.parametrize("operation,args", [
    ("get_definition", (None, "")), ("get_instance", (None, "")), ("subscribe", (None, "")),
    ("create_instance", (None, {"approval_code": "a", "open_id": "ou_x", "form": "[]"})),
])
def test_invalid_identifiers_and_missing_uuid_are_rejected(client, operation, args):
    api, _ = client
    with pytest.raises(ValidationError):
        getattr(api, operation)(*args)


@pytest.mark.parametrize("payload", [None, [], {"code": 123, "msg": "secret detail"}, {"code": 0, "data": []}, {}])
def test_malformed_or_platform_error_responses_are_safe(client, payload):
    api, http = client
    http.response = Response(payload)
    with pytest.raises(ValidationError) as error:
        api.get_definition(object(), "approval")
    assert "secret detail" not in str(error.value)


def test_non_json_response_is_safe(client):
    api, http = client
    class BrokenResponse:
        def json(self):
            raise ValueError("sensitive body")
    http.response = BrokenResponse()
    with pytest.raises(ValidationError) as error:
        api.get_definition(object(), "approval")
    assert "sensitive body" not in str(error.value)


def test_non_2xx_provider_code_survives_guard_without_body_leak():
    from unittest.mock import patch
    from django.test import override_settings
    from apps.integrations.feishu_native_client import _native_http, FeishuNativeAPIError
    from apps.integrations.net_guard import HttpResponse
    response = HttpResponse(400, {}, '{"code":1390003,"msg":"sensitive provider content"}')
    with override_settings(LIVE_PLATFORM_ALLOWED_HOSTS=['open.feishu.cn']), patch('apps.integrations.net_guard.get_runtime_setting', side_effect=lambda *a, default=None: default), patch('apps.integrations.feishu_native_client._default_transport',return_value=response):
        http = _native_http(); api = FeishuNativeClient(identity=FakeIdentity(http))
        with pytest.raises(FeishuNativeAPIError) as error: api.get_instance(object(),'submission-uuid')
        assert error.value.provider_code == 1390003
        assert 'sensitive provider content' not in str(error.value)


def test_existing_subscription_is_safe_to_repeat(client):
    api, http = client
    http.response = Response({'code':1390007,'msg':'subscription existed'})
    assert api.subscribe(object(),'approval-1') == {}
