from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.integrations import ads_binding_compat as compat
from apps.integrations import oauth_state_service
from apps.integrations import tiktok_callback_settings
from apps.integrations.oauth_state_service import _configuration_digest
from apps.integrations.production_settings import SAFE_DEFAULTS


class Versions:
    def __init__(self, rows):
        self.rows = rows
    def select_related(self, *_): return self
    def filter(self, **_): return self
    def order_by(self, *_): return self
    def __getitem__(self, key): return self.rows[key]


def setup(monkeypatch, *, old=None, current=None, version_id=36, current_version_id=38, config=None):
    current = deepcopy(current or SAFE_DEFAULTS)
    old = deepcopy(old or SAFE_DEFAULTS)
    version = SimpleNamespace(pk=version_id, value=old)
    monkeypatch.setattr(compat, "get_effective_runtime_version", lambda: SimpleNamespace(pk=current_version_id))
    monkeypatch.setattr(compat, "get_runtime_platform_config", lambda _p: current["platforms"]["tiktok"])
    monkeypatch.setattr(compat, "_environment_config", lambda: deepcopy(SAFE_DEFAULTS))
    monkeypatch.setattr(tiktok_callback_settings, "callback_setting", lambda advertising=False: "")
    from apps.integrations import models
    monkeypatch.setattr(models, "marketplace_authorization_api_type", lambda _config: "shop")
    monkeypatch.setattr(compat, "marketplace_authorization_api_type", lambda _config: "advertising")
    monkeypatch.setattr(compat, "runtime_snapshot", lambda: {"valid": True})
    monkeypatch.setattr(compat.TenantConfigVersion.objects, "select_related", lambda *_: Versions([version]))
    defaults = dict(platform="tiktok", config_version=1, credential_reference_version=1,
        credential_key_version=1, credential_fingerprint="fingerprint", credential_id="credential",
        credential_status="configured", callback_url="https://example.test/callback",
        platform_config={}, environment="production", contract_version="v1", scopes=["read"],
        regions=[], network_enabled=True, status="active", deleted_at=None)
    return SimpleNamespace(**defaults) if config is None else config, version, current


def test_exact_current_digest_accepted(monkeypatch):
    config, version, current = setup(monkeypatch)
    monkeypatch.setattr(compat.TenantConfigVersion.objects, "select_related", lambda *_: Versions([]))
    digest = _configuration_digest(config, 38, current["platforms"]["tiktok"])
    assert compat.accepts_bound_session_digest(config, digest)


def test_historical_digest_accepts_only_unrelated_runtime_delta(monkeypatch):
    old = deepcopy(SAFE_DEFAULTS)
    current = deepcopy(old)
    old["platforms"]["tiktok"]["affiliate_seller_creator_read_approved"] = True
    current["platforms"]["tiktok"]["affiliate_seller_creator_read_approved"] = False
    config, version, _ = setup(monkeypatch, old=old, current=current)
    digest = _configuration_digest(config, version.pk, old["platforms"]["tiktok"])
    assert compat.accepts_bound_session_digest(config, digest)


@pytest.mark.parametrize("field,value", [
    ("app_id", "changed"), ("auth_url", "https://changed.invalid"),
    ("contract_approved", False), ("market", "US"), ("unrecognized_runtime_key", True),
])
def test_unknown_or_contract_runtime_changes_rejected(monkeypatch, field, value):
    old = deepcopy(SAFE_DEFAULTS)
    old["platforms"]["tiktok"]["contract_approved"] = True
    old["platforms"]["tiktok"].pop("creator_query_bindings", None)
    current = deepcopy(old)
    current["platforms"]["tiktok"][field] = value
    config, version, _ = setup(monkeypatch, old=old, current=current)
    digest = _configuration_digest(config, version.pk, old["platforms"]["tiktok"])
    assert not compat.accepts_bound_session_digest(config, digest)


def test_historical_creator_bindings_default_omission_is_reconstructed(monkeypatch):
    old = deepcopy(SAFE_DEFAULTS)
    old["platforms"]["tiktok"].pop("creator_query_bindings", None)
    current = deepcopy(SAFE_DEFAULTS)
    config, version, _ = setup(monkeypatch, old=old, current=current)
    digest = _configuration_digest(config, version.pk, old["platforms"]["tiktok"])
    assert compat.accepts_bound_session_digest(config, digest)


def test_unverified_digest_and_non_tiktok_rejected(monkeypatch):
    config, _, _ = setup(monkeypatch)
    assert not compat.accepts_bound_session_digest(config, "not-a-matching-digest")
    config.platform = "shopee"
    assert not compat.accepts_bound_session_digest(config, "legacy")


def test_invalid_runtime_fails_closed(monkeypatch):
    config, _, current = setup(monkeypatch)
    current["platforms"]["tiktok"]["auth_url"] = "javascript:bad"
    assert not compat.accepts_bound_session_digest(config, "anything")




@pytest.mark.parametrize("field,value", [
    ("credential_id", "changed"), ("credential_fingerprint", "changed"),
    ("callback_url", "https://changed.invalid/callback"),
    ("scopes", ["different"]), ("platform_config", {"app_id": "99999"}),
    ("config_version", 2), ("regions", ["TH"]),
])
def test_ads_identity_or_configuration_changes_rejected(monkeypatch, field, value):
    config, version, current = setup(monkeypatch)
    digest = _configuration_digest(config, version.pk, current["platforms"]["tiktok"])
    setattr(config, field, value)
    assert not compat.accepts_bound_session_digest(config, digest)


def test_invalid_snapshot_rejects_even_well_formed_projection(monkeypatch):
    config, version, current = setup(monkeypatch)
    digest = _configuration_digest(config, version.pk, current["platforms"]["tiktok"])
    monkeypatch.setattr(compat, "runtime_snapshot", lambda: {"valid": False})
    assert not compat.accepts_bound_session_digest(config, digest)


def test_shop_configuration_cannot_use_ads_compatibility(monkeypatch):
    config, version, current = setup(monkeypatch)
    digest = _configuration_digest(config, version.pk, current["platforms"]["tiktok"])
    monkeypatch.setattr(compat, "marketplace_authorization_api_type", lambda _config: "shop")
    assert not compat.accepts_bound_session_digest(config, digest)


def test_new_schema_shape_on_older_runtime_version_is_preserved(monkeypatch):
    old = deepcopy(SAFE_DEFAULTS)
    old["platforms"]["tiktok"].pop("creator_query_bindings", None)
    config, version, current = setup(monkeypatch, old=old)
    digest = _configuration_digest(config, version.pk, current["platforms"]["tiktok"])
    assert compat.accepts_bound_session_digest(config, digest)
