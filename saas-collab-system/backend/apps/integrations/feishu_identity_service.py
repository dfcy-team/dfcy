from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import ValidationError
from urllib.parse import urlencode
import unicodedata

from .custody import CustodyError, get_custody_backend
from .net_guard import PlatformHttpClient
from .oauth_errors import OAuthFlowError


FEISHU_BASE_URL = "https://open.feishu.cn"
MAX_DIRECTORY_DEPARTMENTS = 100
MAX_DIRECTORY_USERS = 1000
MAX_NAME_CANDIDATES = 20
PAGE_SIZE = 50


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

    @staticmethod
    def _normalized(value):
        return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()

    @staticmethod
    def _local_department_names(user):
        try:
            profile = user.internal_profile
        except (AttributeError, ObjectDoesNotExist):
            return set()
        names = {profile.department.name} if profile.department else set()
        names.update(profile.departments.values_list("name", flat=True))
        return {FeishuIdentityService._normalized(name) for name in names if name}

    def _get_pages(self, *, path, token, message):
        page_token = ""
        while True:
            separator = "&" if "?" in path else "?"
            url = f"{FEISHU_BASE_URL}{path}"
            if page_token:
                url = f"{url}{separator}{urlencode({'page_token': page_token})}"
            response = self.http.request(
                "GET", url, headers={"Authorization": f"Bearer {token}"}, retry=False,
                diagnostic_platform="feishu",
            )
            data = self._payload(response, message).get("data") or {}
            yield data
            if not data.get("has_more") or not data.get("page_token"):
                break
            page_token = str(data["page_token"])

    def _find_by_name(self, *, token, user):
        target_name = self._normalized(user.full_name)
        if not target_name:
            return []
        local_departments = self._local_department_names(user)
        queue = [("0", "")]
        visited = set()
        users_seen = 0
        candidates = {}
        while queue and len(visited) < MAX_DIRECTORY_DEPARTMENTS and users_seen < MAX_DIRECTORY_USERS:
            department_id, department_name = queue.pop(0)
            if department_id in visited:
                continue
            visited.add(department_id)
            user_path = (
                "/open-apis/contact/v3/users/find_by_department?"
                + urlencode({
                    "department_id": department_id, "department_id_type": "open_department_id",
                    "user_id_type": "open_id", "page_size": PAGE_SIZE,
                })
            )
            for data in self._get_pages(token=token, path=user_path, message="飞书通讯录用户查询失败，请检查通讯录权限和应用可用范围。"):
                for item in data.get("items") or []:
                    users_seen += 1
                    if users_seen > MAX_DIRECTORY_USERS:
                        break
                    open_id = str(item.get("open_id") or item.get("user_id") or "").strip()
                    if not open_id or self._normalized(item.get("name")) != target_name:
                        continue
                    department_match = bool(
                        department_name and self._normalized(department_name) in local_departments
                    )
                    candidate = {
                        "open_id": open_id,
                        "user_id": str(item.get("user_id") or ""),
                        "union_id": str(item.get("union_id") or ""),
                        "name": str(item.get("name") or ""),
                        "department_ids": item.get("department_ids") or ([department_id] if department_id != "0" else []),
                        "email": _mask_email(item.get("email") or ""),
                        "phone": _mask_phone(item.get("mobile") or ""),
                        "match_reason": "姓名与部门一致" if department_match else "姓名一致，需人工确认",
                        "match_level": "name_department" if department_match else "name_only",
                    }
                    previous = candidates.get(open_id)
                    if previous is None or (candidate["match_level"] == "name_department" and previous["match_level"] == "name_only"):
                        candidates[open_id] = candidate
            if len(candidates) >= MAX_NAME_CANDIDATES or users_seen >= MAX_DIRECTORY_USERS:
                break
            child_path = (
                f"/open-apis/contact/v3/departments/{department_id}/children?"
                + urlencode({"department_id_type": "open_department_id", "page_size": PAGE_SIZE})
            )
            for data in self._get_pages(token=token, path=child_path, message="飞书部门查询失败，请检查通讯录权限和应用可用范围。"):
                for child in data.get("items") or []:
                    child_id = str(child.get("open_department_id") or child.get("department_id") or "").strip()
                    if child_id and child_id not in visited and len(queue) + len(visited) < MAX_DIRECTORY_DEPARTMENTS:
                        queue.append((child_id, str(child.get("name") or "")))
        return sorted(
            candidates.values(),
            key=lambda item: (item["match_level"] != "name_department", item["name"], item["open_id"]),
        )[:MAX_NAME_CANDIDATES]

    def find_candidates(self, *, connection, user):
        emails = [user.email.strip()] if user.email and user.email.strip() else []
        mobiles = [user.phone.strip()] if user.phone and user.phone.strip() else []
        if not emails and not mobiles and not str(user.full_name or "").strip():
            raise ValidationError({"reason": "missing_identity_fields", "message": "该系统用户未配置姓名、邮箱或手机号，无法查询飞书用户。"})
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
            if emails or mobiles:
                lookup_response = self.http.request(
                    "POST",
                    f"{FEISHU_BASE_URL}/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id",
                    json_body={"emails": emails, "mobiles": mobiles},
                    headers={"Authorization": f"Bearer {token}"},
                    retry=False,
                    diagnostic_platform="feishu",
                )
                lookup_payload = self._payload(lookup_response, "飞书用户查询失败，请检查通讯录权限和应用可用范围。")
            else:
                lookup_payload = {"data": {"user_list": []}}
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
                "match_reason": "邮箱或手机号精确匹配",
                "match_level": "exact_contact",
            })
        if candidates:
            return candidates
        try:
            candidates = self._find_by_name(token=token, user=user)
        except OAuthFlowError as exc:
            raise ValidationError({"reason": "directory_lookup_failed", "message": "飞书通讯录查询失败，请检查权限和应用可用范围。"}) from exc
        if not candidates:
            raise ValidationError({
                "reason": "no_matching_feishu_user",
                "message": "未找到匹配的飞书用户：已尝试邮箱/手机号精确查询及姓名通讯录候选查询。",
            })
        return candidates
