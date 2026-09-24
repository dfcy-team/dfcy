from rest_framework.exceptions import ValidationError

from .custody import CustodyError, get_custody_backend
from .net_guard import PlatformHttpClient
from .oauth_errors import OAuthFlowError


FEISHU_BASE_URL = "https://open.feishu.cn"


def _mask_email(value):
    local, separator, domain = str(value or "").partition("@")
    if not separator:
        return ""
    visible = local[:1]
    return f"{visible}{'*' * max(2, len(local) - 1)}@{domain}"


def _mask_phone(value):
    value = str(value or "")
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def masked_contacts(user):
    return {"email": _mask_email(user.email), "phone": _mask_phone(user.phone)}


class FeishuIdentityService:
    def __init__(self, *, http=None, custody=None):
        self.http = http or PlatformHttpClient(max_retries=1)
        self.custody = custody or get_custody_backend()

    @staticmethod
    def _payload(response, message):
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": message}) from exc
        if not isinstance(payload, dict) or payload.get("code") not in (None, 0):
            raise ValidationError({"detail": message})
        return payload

    def find_candidates(self, *, connection, user):
        emails = [user.email.strip()] if user.email and user.email.strip() else []
        mobiles = [user.phone.strip()] if user.phone and user.phone.strip() else []
        if not emails and not mobiles:
            raise ValidationError({"detail": "该系统用户未配置邮箱或手机号，无法查询飞书用户。"})
        if not connection or not connection.enabled or not connection.app_id or not connection.app_secret_ref:
            raise ValidationError({"detail": "请先启用并完成飞书应用连接配置。"})
        try:
            app_secret = self.custody.retrieve_secret(connection.app_secret_ref)
            token_response = self.http.request(
                "POST",
                f"{FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
                json_body={"app_id": connection.app_id, "app_secret": app_secret},
                retry=False,
                diagnostic_platform="feishu",
            )
            token_payload = self._payload(token_response, "飞书应用认证失败。")
            token = token_payload.get("tenant_access_token")
            if not token:
                raise ValidationError({"detail": "飞书应用认证未返回有效访问凭证。"})
            lookup_response = self.http.request(
                "POST",
                f"{FEISHU_BASE_URL}/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id",
                json_body={"emails": emails, "mobiles": mobiles},
                headers={"Authorization": f"Bearer {token}"},
                retry=False,
                diagnostic_platform="feishu",
            )
            lookup_payload = self._payload(lookup_response, "飞书用户查询失败，请检查通讯录权限和应用可用范围。")
        except CustodyError as exc:
            raise ValidationError({"detail": "无法读取飞书应用凭据。"}) from exc
        except OAuthFlowError as exc:
            raise ValidationError({"detail": f"飞书平台请求失败：{exc}"}) from exc

        candidates = []
        seen = set()
        for item in (lookup_payload.get("data") or {}).get("user_list") or []:
            open_id = str(item.get("user_id") or "").strip()
            if not open_id or open_id in seen:
                continue
            seen.add(open_id)
            detail = {}
            try:
                detail_response = self.http.request(
                    "GET",
                    f"{FEISHU_BASE_URL}/open-apis/contact/v3/users/{open_id}?user_id_type=open_id&department_id_type=open_department_id",
                    headers={"Authorization": f"Bearer {token}"}, retry=False, diagnostic_platform="feishu",
                )
                detail = ((self._payload(detail_response, "飞书用户详情查询失败。").get("data") or {}).get("user") or {})
            except (OAuthFlowError, ValidationError):
                # The exact ID remains useful when optional basic-profile access is absent.
                detail = {}
            candidates.append({
                "open_id": open_id,
                "user_id": str(detail.get("user_id") or ""),
                "union_id": str(detail.get("union_id") or ""),
                "name": str(detail.get("name") or ""),
                "department_ids": detail.get("department_ids") or [],
                "email": _mask_email(detail.get("email") or item.get("email") or ""),
                "phone": _mask_phone(detail.get("mobile") or item.get("mobile") or ""),
            })
        return candidates
