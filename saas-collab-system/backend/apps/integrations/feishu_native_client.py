"""HTTP client for Feishu's native approval APIs."""

import json
from urllib.parse import quote

from rest_framework.exceptions import ValidationError

from .feishu_identity_service import FEISHU_BASE_URL, FeishuIdentityService
from .net_guard import PlatformHttpClient, _default_transport
from .oauth_errors import OAuthFlowError


def _native_http():
    # Preserve only the numeric provider code when the shared guard rejects HTTP
    # failures. The normal allowlist, TLS, timeout and retry policy still applies.
    client = None
    def transport(*args, **kwargs):
        response = _default_transport(*args, **kwargs)
        try:
            data = response.json()
        except (ValueError, TypeError):
            data = {}
        code = data.get('code') if isinstance(data, dict) else None
        client.native_provider_code = code if type(code) is int and code != 0 else None
        return response
    client = PlatformHttpClient(transport=transport, max_retries=0)
    client.native_provider_code = None
    return client


class FeishuNativeAPIError(ValidationError):
    def __init__(self, message, provider_code=None):
        self.provider_code = provider_code
        super().__init__({'detail': message})


class FeishuNativeClient:
    def __init__(self, *, identity=None, http=None):
        self.identity = identity or FeishuIdentityService(http=http or _native_http())

    @staticmethod
    def _response_data(response, message):
        try:
            payload = response.json()
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({"detail": message}) from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise FeishuNativeAPIError(message, payload.get("code") if isinstance(payload, dict) else None)
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise ValidationError({"detail": message})
        return data

    def _request(self, connection, method, path, *, message, json_body=None):
        if hasattr(self.identity.http, 'native_provider_code'):
            self.identity.http.native_provider_code = None
        try:
            token = self.identity._tenant_token(connection)
            response = self.identity.http.request(
                method,
                f"{FEISHU_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json_body=json_body,
                retry=False,
                diagnostic_platform="feishu",
            )
            return self._response_data(response, message)
        except OAuthFlowError as exc:
            code = getattr(self.identity.http, 'native_provider_code', None)
            if type(code) is int:
                raise FeishuNativeAPIError(message, code) from exc
            raise ValidationError({'detail': message}) from exc

    def get_definition(self, connection, approval_code):
        code = str(approval_code or "").strip()
        if not code:
            raise ValidationError({"approval_code": "请提供有效的飞书审批定义编码。"})
        return self._request(
            connection, "GET", f"/open-apis/approval/v4/approvals/{quote(code, safe='')}",
            message="无法读取飞书审批定义。",
        )

    def create_instance(self, connection, payload):
        if not isinstance(payload, dict):
            raise ValidationError({"detail": "飞书审批实例参数无效。"})
        body = dict(payload)
        if not str(body.get("uuid") or "").strip():
            raise ValidationError({"uuid": "请提供稳定的审批实例幂等 UUID。"})
        if not str(body.get("open_id") or "").strip():
            raise ValidationError({"open_id": "请提供审批发起人的 Open ID。"})
        if not body.get("approval_code"):
            raise ValidationError({"approval_code": "请提供审批定义编码。"})
        if "form" not in body:
            raise ValidationError({"form": "请提供审批表单内容。"})
        if not isinstance(body["form"], str):
            try:
                body["form"] = json.dumps(body["form"], ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError) as exc:
                raise ValidationError({"form": "审批表单内容无效。"}) from exc
        return self._request(
            connection, "POST", "/open-apis/approval/v4/instances",
            message="创建飞书审批实例失败。", json_body=body,
        )

    def get_instance(self, connection, instance_code):
        code = str(instance_code or "").strip()
        if not code:
            raise ValidationError({"instance_code": "请提供有效的飞书审批实例编码。"})
        return self._request(
            connection, "GET", f"/open-apis/approval/v4/instances/{quote(code, safe='')}?user_id_type=open_id",
            message="无法读取飞书审批实例。",
        )

    def subscribe(self, connection, approval_code):
        code = str(approval_code or "").strip()
        if not code:
            raise ValidationError({"approval_code": "请提供有效的飞书审批定义编码。"})
        try:
            return self._request(
                connection, "POST", f"/open-apis/approval/v4/approvals/{quote(code, safe='')}/subscribe",
                message="订阅飞书审批事件失败。", json_body={},
            )
        except FeishuNativeAPIError as exc:
            if exc.provider_code == 1390007:
                return {}
            raise
