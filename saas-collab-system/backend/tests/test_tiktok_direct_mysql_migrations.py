"""Apply the actual TK additive migrations in a separate disposable MySQL schema."""
import importlib
import uuid

import pytest
from django.apps import apps
from django.db import connection, connections
from django.db.migrations.state import ProjectState

pytestmark = [pytest.mark.django_db(transaction=True),
              pytest.mark.skipif(connection.vendor != "mysql", reason="Disposable MySQL required")]


def test_actual_tk_migrations_apply_on_mysql():
    assert connection.settings_dict["HOST"] == "tkdirect-mysql-20261020"
    assert connection.settings_dict["NAME"].startswith("tkdirect_synthetic")
    name = "tkdirect_probe_" + uuid.uuid4().hex[:12]
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
    state = ProjectState.from_apps(apps)
    state.remove_model("integrations", "tiktokshopbindingsession")
    for model in ("oauthstatesession", "adsoauthsession"):
        for field in ("browser_verifier_hash", "callback_transport"):
            state.remove_field("integrations", model, field)
    for field in ("cleanup_fence", "cleanup_lease_until", "cleanup_attempts", "cleanup_error"):
        state.remove_field("integrations", "adsoauthsession", field)
    from django.db.backends.mysql.base import DatabaseWrapper
    isolated = DatabaseWrapper({**connection.settings_dict, "NAME": name}, alias=name)
    connections[name] = isolated
    try:
        with isolated.constraint_checks_disabled():
            with isolated.schema_editor() as editor:
                editor.create_model(state.apps.get_model("integrations", "OAuthStateSession"))
                editor.create_model(state.apps.get_model("integrations", "AdsOAuthSession"))
            for migration_name in ("0050_tiktok_shop_binding", "0051_ads_authorization_cleanup"):
                module = importlib.import_module("apps.integrations.migrations." + migration_name)
                with isolated.schema_editor() as editor:
                    state = module.Migration(migration_name, "integrations").apply(state, editor)
        with isolated.cursor() as cursor:
            assert "integrations_tiktokshopbindingsession" in isolated.introspection.table_names(cursor)
            for table in ("integrations_oauthstatesession", "integrations_adsoauthsession"):
                fields = {column.name for column in isolated.introspection.get_table_description(cursor, table)}
                assert {"browser_verifier_hash", "callback_transport"} <= fields
            assert {"cleanup_fence", "cleanup_lease_until", "cleanup_attempts", "cleanup_error"} <= fields
    finally:
        isolated.close()
        del connections[name]
    # The approved tmpfs MySQL container owns this schema and is destroyed after testing.
