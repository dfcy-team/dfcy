from types import SimpleNamespace
from unittest.mock import patch

import pytest
from apps.common.exceptions import DataScopeDenied
from apps.common.error_codes import ErrorCode
from apps.permissions import ui_p6_scopes as scopes


def custom(config):
    return {"scope_type": "custom", "config": config, "role_id": 1}


@pytest.mark.parametrize("kind", ["analytics", "lifecycle"])
def test_unrepresentable_business_scope_is_clear_denial_not_unknown_schema(kind):
    with patch.object(scopes, "get_permission_data_scopes", return_value=[custom({"platform_ids": [1], "warehouse_ids": [3]})]):
        with pytest.raises(DataScopeDenied) as exc:
            if kind == "analytics":
                scopes.analytics_dimension_configs(SimpleNamespace(), "analytics.view")
            else:
                scopes.lifecycle_target_allowed(SimpleNamespace(), "lifecycle.view", spu_id=1)
    assert exc.value.error_code == ErrorCode.DATA_SCOPE_UNSUPPORTED
    assert "请联系管理员" in str(exc.value)


@pytest.mark.parametrize("kind", ["analytics", "lifecycle"])
def test_unknown_scope_key_is_still_rejected(kind):
    with patch.object(scopes, "get_permission_data_scopes", return_value=[custom({"warehouse_ids": [3], "warehous_ids": [3]})]):
        with pytest.raises(DataScopeDenied) as exc:
            if kind == "analytics":
                scopes.analytics_dimension_configs(SimpleNamespace(), "analytics.view")
            else:
                scopes.lifecycle_target_allowed(SimpleNamespace(), "lifecycle.view", spu_id=1)
    assert exc.value.error_code == ErrorCode.DATA_SCOPE_INVALID


def test_separate_compatible_role_is_preserved_but_mixed_role_is_not_widened():
    incompatible = custom({"warehouse_ids": [3], "spu_ids": [999]})
    with patch.object(scopes, "get_permission_data_scopes", return_value=[incompatible, custom({"spu_ids": [1]})]):
        assert scopes.lifecycle_target_allowed(SimpleNamespace(), "lifecycle.view", spu_id=1)
        assert not scopes.lifecycle_target_allowed(SimpleNamespace(), "lifecycle.view", spu_id=999)


def test_analytics_compatible_role_preserves_exact_dimension():
    with patch.object(scopes, "get_permission_data_scopes", return_value=[custom({"warehouse_ids": [3]}), custom({"analytics_dimensions": [{"store_id": "6", "platform": "shopee"}]})]):
        assert scopes.analytics_dimension_configs(SimpleNamespace(), "analytics.view") == [{"store_id": "6", "platform": "shopee"}]


@pytest.mark.parametrize("kind", ["analytics", "lifecycle"])
def test_existing_all_role_keeps_tenant_local_all_semantics(kind):
    rows = [custom({"warehouse_ids": [3]}), {"scope_type": "all", "config": {}, "role_id": 2}]
    with patch.object(scopes, "get_permission_data_scopes", return_value=rows):
        if kind == "analytics":
            assert scopes.analytics_dimension_configs(SimpleNamespace(), "analytics.view") is None
        else:
            assert scopes.lifecycle_target_allowed(SimpleNamespace(), "lifecycle.view", spu_id=1)
