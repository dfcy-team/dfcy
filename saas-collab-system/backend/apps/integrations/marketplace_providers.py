"""Marketplace OAuth provider abstraction.

Providers isolate Shopee / TikTok Shop differences (URL parameters, callback
signatures, error shapes) from views. Only synthetic providers are registered:
they simulate platform behaviour and only emit ``synthetic-*`` custody
references. Real HTTP providers require a dedicated approval and are out of
scope for PR-A2.
"""

import hashlib
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from .credential_service import build_reference_metadata, reference_mask
from .oauth_errors import (
    OAUTH_CALLBACK_REJECTED,
    OAUTH_PROVIDER_UNAVAILABLE,
    OAuthFlowError,
)


SYNTHETIC_OAUTH_BASE_URLS = {
    "shopee": "https://synthetic-shopee-oauth.invalid/v2/authorize",
    "tiktok": "https://synthetic-tiktok-oauth.invalid/auth/authorize",
}
SYNTHETIC_TOKEN_TTL = timedelta(hours=24)


def _normalize_platform_id(value):
    normalized = "".join(ch for ch in str(value).lower() if ch.isalnum() or ch in ".-_")
    if not normalized:
        raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Callback platform store identifier is invalid.")
    return normalized[:120]


def synthetic_callback_signature(platform, **fields):
    """Deterministic synthetic HMAC stand-in used by tests and sandbox fixtures."""

    canonical = "&".join(f"{key}={fields[key]}" for key in sorted(fields))
    return hashlib.sha256(f"synthetic-signature:{platform}:{canonical}".encode()).hexdigest()


class MarketplaceOAuthProvider:
    platform = None

    def build_authorization_url(self, context):
        raise NotImplementedError

    def validate_callback(self, query_params, context):
        raise NotImplementedError

    def exchange_authorization_code(self, callback_data):
        raise NotImplementedError

    def refresh_authorization(self, authorization):
        raise NotImplementedError

    def revoke_authorization(self, authorization):
        raise NotImplementedError

    def fetch_authorized_stores(self, authorization):
        raise NotImplementedError

    def normalize_error(self, error):
        if isinstance(error, OAuthFlowError):
            return error.controlled_code
        provider_status = getattr(error, "provider_status", None)
        if provider_status == 429 or (isinstance(provider_status, int) and provider_status >= 500):
            return OAUTH_PROVIDER_UNAVAILABLE
        return OAUTH_CALLBACK_REJECTED


class SyntheticMarketplaceOAuthProvider(MarketplaceOAuthProvider):
    """Shared synthetic behaviour: signature check and reference-only results."""

    code_param = "code"
    signature_param = "sign"

    def _authorization_params(self, context):
        raise NotImplementedError

    def build_authorization_url(self, context):
        params = {
            **self._authorization_params(context),
            "state": context["state"],
            "redirect": context["redirect_uri"],
        }
        query = "&".join(f"{key}={params[key]}" for key in sorted(params))
        return {"url": f"{SYNTHETIC_OAUTH_BASE_URLS[self.platform]}?{query}", "params": params}

    def _required_callback_fields(self):
        return (self.code_param, "state", "shop_id")

    def _signature_fields(self, query_params):
        return {key: str(query_params[key]) for key in self._required_callback_fields()}

    def validate_callback(self, query_params, context):
        missing = [key for key in (*self._required_callback_fields(), self.signature_param) if not query_params.get(key)]
        if missing:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Callback is missing required platform parameters.")
        if str(query_params["state"]) != str(context.get("state", "")):
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Callback state does not match the consumed session.")
        expected = synthetic_callback_signature(self.platform, **self._signature_fields(query_params))
        if str(query_params[self.signature_param]) != expected:
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Callback signature verification failed.")
        return self._callback_payload(query_params, context)

    def _callback_payload(self, query_params, context):
        return {
            "platform_store_id": _normalize_platform_id(query_params["shop_id"]),
            "region": context.get("region", ""),
            "authorization_code_present": bool(query_params.get(self.code_param)),
        }

    def _synthetic_subject(self, callback_data):
        return f"synthetic-{self.platform}-merchant-{callback_data['platform_store_id']}"

    def exchange_authorization_code(self, callback_data):
        if not callback_data.get("authorization_code_present"):
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "Authorization code was not exchanged.")
        store_slug = callback_data["platform_store_id"]
        credential_id = f"synthetic-{self.platform}-credential-{store_slug}"
        token_id = f"synthetic-{self.platform}-token-{store_slug}"
        metadata = build_reference_metadata(credential_id, token_id, 1)
        subject = self._synthetic_subject(callback_data)
        return {
            "credential_id": metadata["credential_id"],
            "token_id": metadata["token_id"],
            "credential_mask": metadata["credential_mask"],
            "reference_version": 1,
            "expires_at": timezone.now() + SYNTHETIC_TOKEN_TTL,
            "authorized_scopes": list(callback_data.get("scopes") or []),
            "platform_subject": subject,
            "platform_store_records": [
                {
                    "platform_store_id": store_slug,
                    "region": callback_data.get("region", ""),
                    "merchant_subject_id": subject,
                    **self._extra_store_fields(callback_data),
                }
            ],
            "provider_request_id_mask": reference_mask(f"synthetic-{self.platform}-request-{store_slug}"),
        }

    def _extra_store_fields(self, callback_data):
        return {}

    def refresh_authorization(self, authorization):
        store_slug = _normalize_platform_id(authorization.platform_store_id)
        version = authorization.credential_reference_version + 1
        credential_id = f"synthetic-{self.platform}-credential-{store_slug}-v{version}"
        token_id = f"synthetic-{self.platform}-token-{store_slug}-v{version}"
        metadata = build_reference_metadata(credential_id, token_id, version)
        return {
            "credential_id": metadata["credential_id"],
            "token_id": metadata["token_id"],
            "credential_mask": metadata["credential_mask"],
            "reference_version": version,
            "expires_at": timezone.now() + SYNTHETIC_TOKEN_TTL,
            "provider_request_id_mask": reference_mask(f"synthetic-{self.platform}-refresh-{store_slug}"),
        }

    def revoke_authorization(self, authorization):
        return {"status": "revoked", "error_code": ""}

    def fetch_authorized_stores(self, authorization):
        return [
            {
                "platform_store_id": authorization.platform_store_id,
                "region": authorization.region,
                "merchant_subject_id": authorization.merchant_subject_id,
            }
        ]


class SyntheticShopeeOAuthProvider(SyntheticMarketplaceOAuthProvider):
    platform = "shopee"
    code_param = "code"

    def _authorization_params(self, context):
        return {"partner_id": "synthetic-shopee-partner"}


class SyntheticTikTokOAuthProvider(SyntheticMarketplaceOAuthProvider):
    platform = "tiktok"
    code_param = "auth_code"

    def _authorization_params(self, context):
        return {"app_key": "synthetic-tiktok-app-key"}

    def _required_callback_fields(self):
        return (*super()._required_callback_fields(), "shop_cipher")

    def _callback_payload(self, query_params, context):
        payload = super()._callback_payload(query_params, context)
        shop_cipher = str(query_params.get("shop_cipher") or "").strip()
        if not shop_cipher or len(shop_cipher) > 255 or any(ch.isspace() for ch in shop_cipher):
            raise OAuthFlowError(OAUTH_CALLBACK_REJECTED, "TikTok Shop callback shop_cipher is invalid.")
        payload["shop_cipher"] = shop_cipher
        return payload

    def _extra_store_fields(self, callback_data):
        return {"shop_cipher": callback_data.get("shop_cipher", "")}


_OAUTH_PROVIDERS = {
    SyntheticShopeeOAuthProvider.platform: SyntheticShopeeOAuthProvider(),
    SyntheticTikTokOAuthProvider.platform: SyntheticTikTokOAuthProvider(),
}


def get_oauth_provider(platform):
    provider = _OAUTH_PROVIDERS.get(str(platform or "").lower())
    if provider is None:
        raise ValidationError({"platform": "Unsupported marketplace OAuth platform."})
    return provider

