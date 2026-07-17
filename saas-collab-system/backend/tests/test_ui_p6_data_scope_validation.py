import pytest

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.permissions import ui_p6_scopes
from apps.permissions.models import DataScope


def custom_scope(config):
    return [{"scope_type": DataScope.ScopeType.CUSTOM, "config": config}]


def assert_invalid_scope(monkeypatch, config, action):
    monkeypatch.setattr(
        ui_p6_scopes,
        "get_permission_data_scopes",
        lambda _user, _permission_code: custom_scope(config),
    )
    with pytest.raises(DataScopeDenied) as exc_info:
        action()
    assert exc_info.value.error_code == ErrorCode.DATA_SCOPE_INVALID


def test_permission_scope_rejects_unknown_keys_even_when_a_valid_key_exists(monkeypatch):
    assert_invalid_scope(
        monkeypatch,
        {"platforms": ["mock"], "unexpected": ["value"]},
        lambda: ui_p6_scopes.permission_scope_configs(object(), "integrations.manage", {"platforms"}),
    )


@pytest.mark.parametrize(
    ("config", "action"),
    (
        (
            {"analytics_dimensions": [{"product_id": "not-an-id"}]},
            lambda: ui_p6_scopes.analytics_dimension_configs(object(), "analytics.view"),
        ),
        (
            {"spu_ids": [0]},
            lambda: ui_p6_scopes.lifecycle_target_allowed(
                object(),
                "products.lifecycle.view",
                spu_id=1,
            ),
        ),
        (
            {"integration_config_ids": ["not-an-id"]},
            lambda: ui_p6_scopes.integration_values_allowed(
                object(),
                "integrations.manage",
                platform="mock",
                config_id=1,
            ),
        ),
        (
            {"currencies": ["usd"]},
            lambda: ui_p6_scopes.filter_finance_queryset(
                object(),
                object(),
                "finance.view",
            ),
        ),
        (
            {"report_types": [123]},
            lambda: ui_p6_scopes.report_types_for_permission(object(), "reports.view"),
        ),
    ),
)
def test_module_scope_values_are_strictly_validated(monkeypatch, config, action):
    assert_invalid_scope(monkeypatch, config, action)
