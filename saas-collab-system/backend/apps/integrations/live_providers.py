"""Fail-closed Lazada, Shopee and TikTok Shop live OAuth providers."""

import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from django.conf import settings

from .capability import approved_custody_configured, require_live_mode
from .custody import get_custody_backend
from .net_guard import PlatformHttpClient
from .oauth_errors import (
    OAUTH_AUTH_REJECTED,
    OAUTH_CALLBACK_REJECTED,
    OAUTH_PROVIDER_ERROR,
    OAUTH_PROVIDER_UNAVAILABLE,
    OAuthFlowError,
)
from .provider_helpers import ProviderRequestId

PLACEHOLDER = "REPLACE_ME_CONFIRMED_ON_EXECUTION_DAY"


def _required(value, name):
    text = str(value or "").strip()
    if not text or text.startswith("REPLACE_ME"):
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, f"Approved live configuration is missing: {name}.")
    return text


def _expiry(value, *, default_seconds=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    now = datetime.now(timezone.utc)
    if number > int(now.timestamp()):
        return datetime.fromtimestamp(number, tz=timezone.utc)
    return now + timedelta(seconds=number or default_seconds)


def _hmac_sha256(secret, value):
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _tiktok_sign(path, params, secret, body=""):
    filtered = {str(key): str(value) for key, value in params.items() if key not in {"sign", "access_token"}}
    parameter_text = "".join(f"{key}{filtered[key]}" for key in sorted(filtered))
    message = f"{secret}{path}{parameter_text}{body}{secret}"
    return _hmac_sha256(secret, message)


def _lazada_sign(path, params, secret):
    parameter_text = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
    return hmac.new(
        secret.encode("utf-8"),
        f"{path}{parameter_text}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()


class LiveOAuthProviderBase:
    platform = None

    def __init__(self, provider_config, secret_resolver=None, http_client=None, custody=None):
        self.config = dict(provider_config)
        self.http = http_client or PlatformHttpClient()
        self.custody = custody or get_custody_backend()
        self.secret_resolver = secret_resolver

    def _preflight(self, operation):
        require_live_mode(f"{self.platform} {operation}")
        if self.config.get("integration_config_ready") is False:
            raise OAuthFlowError(
                OAUTH_PROVIDER_UNAVAILABLE,
                "The selected integration configuration is not approved for controlled live validation.",
            )
        if not self.config.get("contract_approved"):
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, f"{self.platform} platform contract is not approved.")
        redirect_uri = _required(self.config.get("redirect_uri"), f"{self.platform}.redirect_uri")
        allowlist = set(getattr(settings, "LIVE_OAUTH_REDIRECT_ALLOWLIST", []) or [])
        if redirect_uri not in allowlist:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "OAuth redirect URI is not approved.")

    def _app_id(self):
        return _required(self.config.get("app_id"), f"{self.platform}.app_id")

    def validate_start_configuration(self, redirect_uri):
        self._preflight("authorization")
        if redirect_uri != self.config["redirect_uri"]:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "OAuth redirect URI does not match the approved value.")

    def _app_secret(self):
        if self.secret_resolver is not None:
            resolved = self.secret_resolver(self.platform)
            value = resolved.get("app_secret") if isinstance(resolved, dict) else resolved
            return _required(value, f"{self.platform}.app_secret")
        reference = _required(self.config.get("app_secret_reference"), f"{self.platform}.app_secret_reference")
        return self.custody.retrieve_secret(reference)

    def _request_json(self, method, url, *, headers=None, query=None, json_body=None):
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        response = self.http.request(method, url, headers=headers, json_body=json_body)
        try:
            payload = response.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "Platform returned an invalid response.")
        if not isinstance(payload, dict):
            raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "Platform returned an invalid response.")
        return payload

    @staticmethod
    def _reject_unknown(params, allowed):
        unknown = set(params) - set(allowed)
        if unknown:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Callback contained unexpected parameters.")


class ShopeeLiveOAuthProvider(LiveOAuthProviderBase):
    platform = "shopee"

    def _host(self):
        return _required(self.config.get("api_host"), "shopee.api_host")

    def _signed_public_query(self, path):
        timestamp = int(time.time())
        partner_id = self._app_id()
        return {
            "partner_id": partner_id,
            "timestamp": timestamp,
            "sign": _hmac_sha256(self._app_secret(), f"{partner_id}{path}{timestamp}"),
        }

    def _signed_shop_query(self, path, access_token, shop_id):
        timestamp = int(time.time())
        partner_id = self._app_id()
        base = f"{partner_id}{path}{timestamp}{access_token}{shop_id}"
        return {
            "partner_id": partner_id,
            "timestamp": timestamp,
            "access_token": access_token,
            "shop_id": shop_id,
            "sign": _hmac_sha256(self._app_secret(), base),
        }

    def build_authorization_url(self, context):
        self.validate_start_configuration(context.get("redirect_uri"))
        auth_url = _required(self.config.get("auth_url"), "shopee.auth_url")
        path = urllib.parse.urlparse(auth_url).path
        query = self._signed_public_query(path)
        redirect_parts = list(urllib.parse.urlsplit(self.config["redirect_uri"]))
        redirect_query = urllib.parse.parse_qsl(redirect_parts[3], keep_blank_values=True)
        redirect_query.append(("state", context["state"]))
        redirect_parts[3] = urllib.parse.urlencode(redirect_query)
        query["redirect"] = urllib.parse.urlunsplit(redirect_parts)
        return {"url": f"{auth_url}?{urllib.parse.urlencode(query)}", "provider_request_id": None}

    def validate_callback(self, params, context):
        self._preflight("callback")
        self._reject_unknown(params, {"code", "shop_id", "main_account_id", "state"})
        code = str(params.get("code") or "").strip()
        shop_id = str(params.get("shop_id") or "").strip()
        if not code or not shop_id:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Shopee callback is missing required parameters.")
        return {
            "code": code,
            "platform_store_id": shop_id,
            "merchant_subject_id": str(params.get("main_account_id") or shop_id),
            "region": context.get("region", ""),
            "scopes": list(context.get("scopes") or []),
        }

    def exchange_authorization_code(self, payload):
        self._preflight("token exchange")
        path = _required(self.config.get("token_path"), "shopee.token_path")
        query = self._signed_public_query(path)
        shop_id = payload["platform_store_id"]
        data = self._request_json(
            "POST",
            f"{self._host()}{path}",
            query=query,
            json_body={"code": payload["code"], "shop_id": int(shop_id), "partner_id": int(self._app_id())},
        )
        if data.get("error"):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Shopee rejected the authorization code.")
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or not refresh_token:
            raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "Shopee token response is incomplete.")
        expires_at = _expiry(data.get("expire_in"), default_seconds=0)
        stored = self.custody.store_secrets(
            credential_type="shopee",
            reference_version=1,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at.isoformat(),
            metadata={"platform": "shopee", "shop_id": shop_id},
        )
        try:
            shop = self._fetch_shop_with_token(shop_id, stored["token_id"])
        except Exception:
            self.custody.revoke(stored["credential_id"], stored["token_id"])
            raise
        return {
            **stored,
            "reference_kind": "custody",
            "credential_reference_version": 1,
            "expires_at": expires_at,
            "platform_subject": payload["merchant_subject_id"],
            "authorized_scopes": list(payload.get("scopes") or []),
            "platform_store_records": [shop],
            "provider_request_id_mask": ProviderRequestId.mask(data.get("request_id")),
            "new_reference_revoker": self.custody.revoke,
            "previous_reference_revoker": self.custody.revoke,
        }

    def _fetch_shop_with_token(self, shop_id, token_id):
        path = _required(self.config.get("shop_path"), "shopee.shop_path")
        access_token = self.custody.retrieve_access_token(token_id)
        data = self._request_json("GET", f"{self._host()}{path}", query=self._signed_shop_query(path, access_token, shop_id))
        if data.get("error"):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Shopee shop identity verification failed.")
        response = data.get("response") or data.get("shop_info") or {}
        response_shop_id = str(response.get("shop_id") or shop_id)
        if response_shop_id != str(shop_id):
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Shopee shop identity did not match callback subject.")
        return {"platform_store_id": str(shop_id), "shop_cipher": "", "region": self.config.get("region", "")}

    def refresh_authorization(self, authorization):
        self._preflight("refresh")
        path = _required(self.config.get("refresh_path"), "shopee.refresh_path")
        refresh_token = self.custody.retrieve_refresh_token(authorization.token_id)
        data = self._request_json(
            "POST",
            f"{self._host()}{path}",
            query=self._signed_public_query(path),
            json_body={
                "refresh_token": refresh_token,
                "partner_id": int(self._app_id()),
                "shop_id": int(authorization.platform_store_id),
            },
        )
        if data.get("error") or not data.get("access_token") or not data.get("refresh_token"):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Shopee token refresh failed.")
        version = authorization.credential_reference_version + 1
        expires_at = _expiry(data.get("expire_in"))
        stored = self.custody.store_secrets(
            credential_type="shopee",
            reference_version=version,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at.isoformat(),
            metadata={"platform": "shopee", "shop_id": authorization.platform_store_id},
        )
        return {
            **stored,
            "reference_kind": "custody",
            "reference_version": version,
            "expires_at": expires_at,
            "previous_reference_revoker": self.custody.revoke,
            "new_reference_revoker": self.custody.revoke,
        }

    def revoke_authorization(self, authorization):
        self._preflight("revoke")
        path = _required(self.config.get("revoke_path"), "shopee.revoke_path")
        access_token = self.custody.retrieve_access_token(authorization.token_id)
        data = self._request_json(
            "POST",
            f"{self._host()}{path}",
            query=self._signed_shop_query(path, access_token, authorization.platform_store_id),
            json_body={"shop_id": int(authorization.platform_store_id)},
        )
        if data.get("error"):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Shopee platform revoke failed.")
        result = self.custody.revoke(authorization.credential_id, authorization.token_id)
        if result.get("status") not in {"revoked", "not_required"}:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody revoke failed.")
        return {"status": "revoked"}

    def fetch_authorized_stores(self, authorization):
        self._preflight("shop verification")
        return [self._fetch_shop_with_token(authorization.platform_store_id, authorization.token_id)]


class LazadaLiveOAuthProvider(LiveOAuthProviderBase):
    platform = "lazada"

    def _host(self):
        return _required(self.config.get("api_host"), "lazada.api_host").rstrip("/")

    def _signed_query(self, path, extra=None):
        params = {
            "app_key": self._app_id(),
            "sign_method": "sha256",
            "timestamp": int(time.time() * 1000),
        }
        params.update(extra or {})
        params["sign"] = _lazada_sign(path, params, self._app_secret())
        return params

    @staticmethod
    def _response_error(payload):
        code = payload.get("code")
        return code not in {None, 0, "0"} or bool(payload.get("error"))

    def build_authorization_url(self, context):
        self.validate_start_configuration(context.get("redirect_uri"))
        auth_url = _required(self.config.get("auth_url"), "lazada.auth_url")
        query = {
            "response_type": "code",
            "force_auth": "true",
            "redirect_uri": self.config["redirect_uri"],
            "client_id": self._app_id(),
            "state": context["state"],
        }
        return {"url": f"{auth_url}?{urllib.parse.urlencode(query)}", "provider_request_id": None}

    def validate_callback(self, params, context):
        self._preflight("callback")
        self._reject_unknown(params, {"code", "state", "error", "error_description"})
        code = str(params.get("code") or "").strip()
        if params.get("error") or not code:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Lazada authorization was rejected.")
        return {
            "code": code,
            "region": str(context.get("region") or "").upper(),
            "scopes": list(context.get("scopes") or []),
        }

    def _token_request(self, path, extra):
        payload = self._request_json(
            "POST",
            f"{self._host()}{path}",
            query=self._signed_query(path, extra),
        )
        if self._response_error(payload):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Lazada rejected the token request.")
        return payload

    @staticmethod
    def _store_record(payload, expected_region):
        countries = payload.get("country_user_info") or []
        if not isinstance(countries, list):
            countries = []
        expected_region = str(expected_region or "").upper()
        matched = next(
            (item for item in countries if str(item.get("country") or "").upper() == expected_region),
            None,
        )
        if not matched:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Lazada authorization did not include the selected country store.")
        store_id = str(matched.get("seller_id") or matched.get("user_id") or "").strip()
        if not store_id:
            raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "Lazada seller identity is incomplete.")
        return {
            "platform_store_id": store_id,
            "shop_cipher": "",
            "region": expected_region,
            "merchant_subject_id": str(matched.get("user_id") or store_id),
        }

    def exchange_authorization_code(self, payload):
        self._preflight("token exchange")
        path = _required(self.config.get("token_path"), "lazada.token_path")
        data = self._token_request(path, {"code": payload["code"]})
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or not refresh_token:
            raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "Lazada token response is incomplete.")
        store = self._store_record(data, payload.get("region"))
        expires_at = _expiry(data.get("expires_in"))
        stored = self.custody.store_secrets(
            credential_type="lazada",
            reference_version=1,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at.isoformat(),
            metadata={"platform": "lazada", "region": store["region"], "store_id": store["platform_store_id"]},
        )
        return {
            **stored,
            "reference_kind": "custody",
            "credential_reference_version": 1,
            "expires_at": expires_at,
            "platform_subject": store["merchant_subject_id"],
            "authorized_scopes": list(payload.get("scopes") or []),
            "platform_store_records": [store],
            "provider_request_id_mask": ProviderRequestId.mask(data.get("request_id")),
            "new_reference_revoker": self.custody.revoke,
            "previous_reference_revoker": self.custody.revoke,
        }

    def refresh_authorization(self, authorization):
        self._preflight("refresh")
        path = _required(self.config.get("refresh_path"), "lazada.refresh_path")
        data = self._token_request(
            path,
            {"refresh_token": self.custody.retrieve_refresh_token(authorization.token_id)},
        )
        if not data.get("access_token") or not data.get("refresh_token"):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Lazada token refresh failed.")
        version = authorization.credential_reference_version + 1
        expires_at = _expiry(data.get("expires_in"))
        stored = self.custody.store_secrets(
            credential_type="lazada",
            reference_version=version,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at.isoformat(),
            metadata={"platform": "lazada", "region": authorization.region, "store_id": authorization.platform_store_id},
        )
        return {
            **stored,
            "reference_kind": "custody",
            "reference_version": version,
            "expires_at": expires_at,
            "previous_reference_revoker": self.custody.revoke,
            "new_reference_revoker": self.custody.revoke,
        }

    def revoke_authorization(self, authorization):
        self._preflight("revoke")
        result = self.custody.revoke(authorization.credential_id, authorization.token_id)
        if result.get("status") not in {"revoked", "not_required"}:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody revoke failed.")
        return {"status": "revoked", "platform_revocation": "seller_managed"}

    def fetch_authorized_stores(self, authorization):
        self._preflight("authorized-store verification")
        return [{
            "platform_store_id": authorization.platform_store_id,
            "shop_cipher": "",
            "region": authorization.region,
            "merchant_subject_id": authorization.merchant_subject_id,
        }]


class TikTokLiveOAuthProvider(LiveOAuthProviderBase):
    platform = "tiktok"

    def _market(self):
        market = str(self.config.get("market") or "").upper()
        if market not in {"US", "ROW"}:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "TikTok market must be US or ROW.")
        return market

    def _open_host(self):
        return _required(self.config.get("api_host"), "tiktok.open_api_host")

    def build_authorization_url(self, context):
        self.validate_start_configuration(context.get("redirect_uri"))
        auth_url = _required(self.config.get("auth_url"), f"tiktok.auth_url[{self._market()}]")
        service_id = _required(self.config.get("service_id"), "tiktok.service_id")
        return {
            "url": f"{auth_url}?{urllib.parse.urlencode({'service_id': service_id, 'state': context['state']})}",
            "provider_request_id": None,
        }

    def validate_callback(self, params, context):
        self._preflight("callback")
        self._reject_unknown(params, {"code", "state", "error"})
        if params.get("error") or not str(params.get("code") or "").strip():
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "TikTok authorization was rejected.")
        return {"code": str(params["code"]), "region": context.get("region", ""), "scopes": context.get("scopes", [])}

    def _token_request(self, path, params):
        payload = self._request_json("GET", f"{_required(self.config.get('token_host'), 'tiktok.token_host')}{path}", query=params)
        if payload.get("code") != 0:
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok rejected the token request.")
        data = payload.get("data") or {}
        if "user_type" in data and str(data.get("user_type")) != "0":
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok authorization is not a seller authorization.")
        return data, payload.get("request_id")

    def _signed_open_query(self, path, extra=None):
        params = {"app_key": self._app_id(), "timestamp": int(time.time())}
        params.update(extra or {})
        params["sign"] = _tiktok_sign(path, params, self._app_secret())
        return params

    def _authorized_shops(self, token_id):
        path = _required(self.config.get("authorized_shops_path"), "tiktok.authorized_shops_path")
        access_token = self.custody.retrieve_access_token(token_id)
        payload = self._request_json(
            "GET",
            f"{self._open_host()}{path}",
            query=self._signed_open_query(path),
            headers={"Content-Type": "application/json", "x-tts-access-token": access_token},
        )
        if payload.get("code") != 0:
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok authorized-shop discovery failed.")
        shops = (payload.get("data") or {}).get("shops") or []
        if len(shops) != 1:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Exactly one approved TikTok shop is required.")
        shop = shops[0]
        shop_id = str(shop.get("id") or "").strip()
        cipher = str(shop.get("cipher") or "").strip()
        region = str(shop.get("region") or "").upper()
        if not shop_id or not cipher or not region:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "TikTok authorized-shop identity is incomplete.")
        return {"platform_store_id": shop_id, "shop_cipher": cipher, "region": region}

    def _verify_metadata(self, token_id, shop):
        path = _required(self.config.get("metadata_path"), "tiktok.metadata_path")
        access_token = self.custody.retrieve_access_token(token_id)
        payload = self._request_json(
            "GET",
            f"{self._open_host()}{path}",
            query=self._signed_open_query(path, {"shop_cipher": shop["shop_cipher"]}),
            headers={"Content-Type": "application/json", "x-tts-access-token": access_token},
        )
        if payload.get("code") != 0:
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok minimal metadata verification failed.")

    def exchange_authorization_code(self, payload):
        self._preflight("token exchange")
        data, request_id = self._token_request(
            _required(self.config.get("token_path"), "tiktok.token_path"),
            {
                "app_key": self._app_id(),
                "app_secret": self._app_secret(),
                "auth_code": payload["code"],
                "grant_type": "authorized_code",
            },
        )
        if not data.get("access_token") or not data.get("refresh_token") or not data.get("open_id"):
            raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "TikTok token response is incomplete.")
        scopes = list(data.get("granted_scopes") or data.get("granted_permissions") or [])
        required_scopes = set(payload.get("scopes") or [])
        if not required_scopes.issubset(set(scopes)):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok granted scopes are incomplete.")
        expires_at = _expiry(data.get("access_token_expire_in"))
        stored = self.custody.store_secrets(
            credential_type="tiktok",
            reference_version=1,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at.isoformat(),
            metadata={"platform": "tiktok", "market": self._market()},
        )
        try:
            shop = self._authorized_shops(stored["token_id"])
            expected_region = str(payload.get("region") or "").upper()
            if expected_region and shop["region"] != expected_region:
                raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "TikTok shop region did not match OAuth context.")
            self._verify_metadata(stored["token_id"], shop)
        except Exception:
            self.custody.revoke(stored["credential_id"], stored["token_id"])
            raise
        return {
            **stored,
            "reference_kind": "custody",
            "credential_reference_version": 1,
            "expires_at": expires_at,
            "platform_subject": str(data["open_id"]),
            "authorized_scopes": scopes,
            "platform_store_records": [shop],
            "provider_request_id_mask": ProviderRequestId.mask(request_id),
            "new_reference_revoker": self.custody.revoke,
            "previous_reference_revoker": self.custody.revoke,
        }

    def refresh_authorization(self, authorization):
        self._preflight("refresh")
        refresh_token = self.custody.retrieve_refresh_token(authorization.token_id)
        data, _ = self._token_request(
            _required(self.config.get("refresh_path"), "tiktok.refresh_path"),
            {
                "app_key": self._app_id(),
                "app_secret": self._app_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if not data.get("access_token") or not data.get("refresh_token"):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok token refresh failed.")
        scopes = set(data.get("granted_scopes") or data.get("granted_permissions") or [])
        if not set(authorization.scopes or []).issubset(scopes):
            raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok refreshed token scopes are incomplete.")
        version = authorization.credential_reference_version + 1
        expires_at = _expiry(data.get("access_token_expire_in"))
        stored = self.custody.store_secrets(
            credential_type="tiktok",
            reference_version=version,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at.isoformat(),
            metadata={"platform": "tiktok", "market": self._market()},
        )
        return {
            **stored,
            "reference_kind": "custody",
            "reference_version": version,
            "expires_at": expires_at,
            "previous_reference_revoker": self.custody.revoke,
            "new_reference_revoker": self.custody.revoke,
        }

    def revoke_authorization(self, authorization):
        self._preflight("revoke")
        path = str(self.config.get("revoke_path") or "").strip()
        platform_revocation = "seller_managed"
        if path and not path.startswith("REPLACE_ME"):
            access_token = self.custody.retrieve_access_token(authorization.token_id)
            payload = self._request_json(
                "POST",
                f"{_required(self.config.get('token_host'), 'tiktok.token_host')}{path}",
                json_body={"app_key": self._app_id(), "app_secret": self._app_secret(), "access_token": access_token},
            )
            if payload.get("code") != 0:
                raise OAuthFlowError(OAUTH_AUTH_REJECTED, "TikTok platform revoke failed.")
            platform_revocation = "api"
        result = self.custody.revoke(authorization.credential_id, authorization.token_id)
        if result.get("status") not in {"revoked", "not_required"}:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody revoke failed.")
        return {"status": "revoked", "platform_revocation": platform_revocation}

    def fetch_authorized_stores(self, authorization):
        self._preflight("authorized-shop verification")
        shop = self._authorized_shops(authorization.token_id)
        self._verify_metadata(authorization.token_id, shop)
        return [shop]


def integration_config_oauth_blockers(platform, integration_config):
    """Return non-sensitive reasons that keep a marketplace OAuth config closed."""
    if integration_config is None:
        return ["config_missing"]
    platform = str(platform or "").lower()
    values = dict(getattr(integration_config, "platform_config", {}) or {})
    expected_contract = {"lazada": "open-platform-v1", "shopee": "v2", "tiktok": "202407"}.get(platform, "")
    callback_url = str(getattr(integration_config, "callback_url", "") or "").strip()
    environment = str(getattr(integration_config, "environment", ""))
    status = str(getattr(integration_config, "status", ""))
    credential_status = str(getattr(integration_config, "credential_status", ""))
    expected_callback = {
        "lazada": getattr(settings, "LIVE_LAZADA_REDIRECT_URI", ""),
        "shopee": getattr(settings, "LIVE_SHOPEE_REDIRECT_URI", ""),
        "tiktok": getattr(settings, "LIVE_TIKTOK_REDIRECT_URI", ""),
    }.get(platform, "")
    contract_enabled = {
        "lazada": getattr(settings, "LIVE_LAZADA_CONTRACT_APPROVED", False),
        "shopee": getattr(settings, "LIVE_SHOPEE_CONTRACT_APPROVED", False),
        "tiktok": getattr(settings, "LIVE_TIKTOK_CONTRACT_APPROVED", False),
    }.get(platform, False)
    allowlist = set(getattr(settings, "LIVE_OAUTH_REDIRECT_ALLOWLIST", []) or [])
    blockers = []
    if str(getattr(integration_config, "platform", "")).lower() != platform:
        blockers.append("platform_mismatch")
    if environment not in {"pilot", "production"}:
        blockers.append("environment_not_live")
    if getattr(settings, "PLATFORM_NETWORK_MODE", "") != "approved-live-test":
        blockers.append("platform_network_mode_disabled")
    if not getattr(settings, "LIVE_PLATFORM_SECURITY_APPROVED", False):
        blockers.append("platform_security_not_approved")
    if not approved_custody_configured():
        blockers.append("credential_custody_not_approved")
    if not getattr(settings, "LIVE_PLATFORM_ALLOWED_HOSTS", []):
        blockers.append("outbound_host_allowlist_missing")
    if not contract_enabled:
        blockers.append("platform_contract_not_enabled")
    if not bool(getattr(integration_config, "network_enabled", False)):
        blockers.append("network_not_approved")
    if bool(getattr(integration_config, "sync_write_enabled", False)):
        blockers.append("write_sync_enabled")
    if status not in {"configured", "verified", "active"}:
        blockers.append("config_not_approved")
    if credential_status != "configured":
        blockers.append("credential_not_configured")
    if not bool(getattr(integration_config, "credential_id", "")):
        blockers.append("credential_reference_missing")
    if expected_contract and str(getattr(integration_config, "contract_version", "")) != expected_contract:
        blockers.append("contract_not_approved")
    if not callback_url:
        blockers.append("callback_missing")
    elif not allowlist:
        blockers.append("callback_allowlist_missing")
    elif expected_callback and callback_url != expected_callback:
        blockers.append("callback_mismatch")
    elif allowlist and callback_url not in allowlist:
        blockers.append("callback_not_allowlisted")
    public_app_id = values.get("partner_id") if platform == "shopee" else values.get("app_key")
    if not str(public_app_id or "").strip():
        blockers.append("public_app_id_missing")
    return blockers


def _integration_config_overrides(platform, integration_config):
    if integration_config is None:
        return {}
    if str(getattr(integration_config, "platform", "")).lower() != platform:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Integration configuration platform mismatch.")
    values = dict(getattr(integration_config, "platform_config", {}) or {})
    if platform == "shopee":
        ready = not integration_config_oauth_blockers(platform, integration_config)
    else:
        expected_contract = {"lazada": "open-platform-v1", "tiktok": "202407"}.get(platform, "")
        ready = (
            str(getattr(integration_config, "environment", "")) == "pilot"
            and bool(getattr(integration_config, "network_enabled", False))
            and not bool(getattr(integration_config, "sync_read_enabled", False))
            and not bool(getattr(integration_config, "sync_write_enabled", False))
            and str(getattr(integration_config, "status", "")) in {"configured", "verified"}
            and str(getattr(integration_config, "credential_status", "")) == "configured"
            and bool(getattr(integration_config, "credential_id", ""))
            and str(getattr(integration_config, "contract_version", "")) == expected_contract
        )
    common = {
        "app_secret_reference": str(getattr(integration_config, "credential_id", "") or ""),
        "redirect_uri": str(getattr(integration_config, "callback_url", "") or ""),
        "integration_config_ready": ready,
    }
    if platform == "shopee":
        common["app_id"] = str(values.get("partner_id") or "")
    else:
        common["app_id"] = str(values.get("app_key") or "")
        if platform == "tiktok":
            common["service_id"] = str(values.get("service_id") or "")
    return common


def build_live_provider(platform, integration_config=None, secret_resolver=None, **overrides):
    platform = str(platform or "").lower()
    if platform == "lazada":
        config = {
            "contract_approved": getattr(settings, "LIVE_LAZADA_CONTRACT_APPROVED", False),
            "app_id": getattr(settings, "LIVE_LAZADA_APP_KEY", ""),
            "app_secret_reference": getattr(settings, "LIVE_LAZADA_APP_SECRET_REFERENCE", ""),
            "redirect_uri": getattr(settings, "LIVE_LAZADA_REDIRECT_URI", ""),
            "auth_url": getattr(settings, "LIVE_LAZADA_AUTH_URL", "https://auth.lazada.com/oauth/authorize"),
            "api_host": getattr(settings, "LIVE_LAZADA_API_HOST", "https://api.lazada.com"),
            "token_path": getattr(settings, "LIVE_LAZADA_TOKEN_PATH", "/rest/auth/token/create"),
            "refresh_path": getattr(settings, "LIVE_LAZADA_REFRESH_PATH", "/rest/auth/token/refresh"),
        }
        config.update(overrides)
        config.update(_integration_config_overrides(platform, integration_config))
        return LazadaLiveOAuthProvider(config, secret_resolver=secret_resolver)
    if platform == "shopee":
        config = {
            "contract_approved": getattr(settings, "LIVE_SHOPEE_CONTRACT_APPROVED", False),
            "app_id": getattr(settings, "LIVE_SHOPEE_PARTNER_ID", ""),
            "app_secret_reference": getattr(settings, "LIVE_SHOPEE_APP_SECRET_REFERENCE", ""),
            "redirect_uri": getattr(settings, "LIVE_SHOPEE_REDIRECT_URI", ""),
            "auth_url": getattr(settings, "LIVE_SHOPEE_AUTH_URL", PLACEHOLDER),
            "api_host": getattr(settings, "LIVE_SHOPEE_DEFAULT_HOST", PLACEHOLDER),
            "token_path": getattr(settings, "LIVE_SHOPEE_TOKEN_PATH", PLACEHOLDER),
            "refresh_path": getattr(settings, "LIVE_SHOPEE_REFRESH_PATH", PLACEHOLDER),
            "revoke_path": getattr(settings, "LIVE_SHOPEE_REVOKE_PATH", PLACEHOLDER),
            "shop_path": getattr(settings, "LIVE_SHOPEE_SHOP_PATH", PLACEHOLDER),
            "region": getattr(settings, "LIVE_SHOPEE_DEFAULT_REGION", ""),
        }
        config.update(overrides)
        config.update(_integration_config_overrides(platform, integration_config))
        return ShopeeLiveOAuthProvider(config, secret_resolver=secret_resolver)
    if platform == "tiktok":
        market = str(getattr(settings, "LIVE_TIKTOK_MARKET", "ROW")).upper()
        auth_urls = getattr(settings, "LIVE_TIKTOK_AUTH_URLS", {}) or {}
        open_hosts = getattr(settings, "LIVE_TIKTOK_OPEN_API_HOSTS", {}) or {}
        config = {
            "contract_approved": getattr(settings, "LIVE_TIKTOK_CONTRACT_APPROVED", False),
            "app_id": getattr(settings, "LIVE_TIKTOK_APP_KEY", ""),
            "app_secret_reference": getattr(settings, "LIVE_TIKTOK_APP_SECRET_REFERENCE", ""),
            "service_id": getattr(settings, "LIVE_TIKTOK_SERVICE_ID", ""),
            "redirect_uri": getattr(settings, "LIVE_TIKTOK_REDIRECT_URI", ""),
            "market": market,
            "auth_url": auth_urls.get(market) or getattr(settings, "LIVE_TIKTOK_DEFAULT_AUTH_URL", PLACEHOLDER),
            "api_host": open_hosts.get(market) or getattr(settings, "LIVE_TIKTOK_DEFAULT_OPEN_HOST", PLACEHOLDER),
            "token_host": getattr(settings, "LIVE_TIKTOK_TOKEN_HOST", "https://auth.tiktok-shops.com"),
            "token_path": getattr(settings, "LIVE_TIKTOK_TOKEN_PATH", PLACEHOLDER),
            "refresh_path": getattr(settings, "LIVE_TIKTOK_REFRESH_PATH", PLACEHOLDER),
            "revoke_path": getattr(settings, "LIVE_TIKTOK_REVOKE_PATH", PLACEHOLDER),
            "authorized_shops_path": getattr(settings, "LIVE_TIKTOK_AUTHORIZED_SHOPS_PATH", PLACEHOLDER),
            "metadata_path": getattr(settings, "LIVE_TIKTOK_METADATA_PATH", PLACEHOLDER),
        }
        config.update(overrides)
        config.update(_integration_config_overrides(platform, integration_config))
        return TikTokLiveOAuthProvider(config, secret_resolver=secret_resolver)
    raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Unsupported live marketplace platform.")
