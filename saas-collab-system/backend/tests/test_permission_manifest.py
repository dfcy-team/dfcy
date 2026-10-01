import pytest

from apps.permissions.catalog_governance import build_manifest, classify_endpoint, manifest_diff


class DeclaredApplicationPermission: pass


class SampleView:
    http_method_names = ["get", "post", "delete"]
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sample.view"
    write_permission_code = "sample.manage"
    __module__ = "apps.sample.views"
    def get(self): pass
    def post(self): pass
    def delete(self): pass


def test_manifest_hash_and_order_are_deterministic():
    defs = [{"code": "sample.view", "name": "View", "module": "sample", "action": "view"}]
    rows = classify_endpoint("sample/", type("Callback", (), {"cls": SampleView}), {"sample.view": defs[0], "sample.manage": {}})
    a = build_manifest(defs, list(rows))
    b = build_manifest(list(reversed(defs)), list(reversed(rows)))
    assert a == b
    assert {x["method"]: x["action"] for x in a["endpoints"]} == {"GET": "read", "HEAD": "read", "POST": "create", "DELETE": "delete"}


def test_permission_rename_retaining_code_is_metadata_change():
    a = build_manifest([{"code": "sample.view", "name": "Old", "menu_path": "A"}], [])
    b = build_manifest([{"code": "sample.view", "name": "New", "menu_path": "B"}], [])
    diff = manifest_diff(a, b)
    assert diff["changed"] == 1 and diff["added"] == diff["removed"] == 0


def test_deleted_and_added_actions_are_detected_and_high_risk_reported():
    old = {"permissions": [], "endpoints": [{"route": "x/", "method": "POST", "action": "create", "risk": "high"}]}
    new = {"permissions": [], "endpoints": [{"route": "y/", "method": "DELETE", "action": "delete", "risk": "critical"}]}
    diff = manifest_diff(old, new)
    assert diff["added"] == diff["removed"] == 1
    assert len(diff["high_risk"]) == 2


def test_specialized_channel_is_explicit_review_required():
    class SpecializedView:
        http_method_names = ["get", "post"]
        permission_classes = [type("IsExternalUser", (), {})]
        __module__ = "apps.supplier.views"
    rows = classify_endpoint("external/", type("Callback", (), {"cls": SpecializedView}), {})
    assert all(r["action"] == "review_required" and r["owner"] == "supplier" for r in rows)
    assert all(r["permission_classes"] == ["IsExternalUser"] for r in rows)


def test_unimplemented_methods_are_not_emitted_and_options_are_exempt():
    class PartialView:
        http_method_names = ["get", "post", "put", "options"]
        permission_classes = []
        def get(self): pass
        __module__ = "apps.sample.views"
    rows = classify_endpoint("partial/", type("Callback", (), {"cls": PartialView}), {})
    assert {(r["method"], r["action"]) for r in rows} == {("GET", "read"), ("HEAD", "read"), ("OPTIONS", "exempt")}
    assert all(r["policy"] == "public_handler_guard" for r in rows if r["method"] != "OPTIONS")


def test_specialized_method_and_or_codes_are_checked_against_catalog():
    class Guard:
        read_permission_code = "example.view"
        write_permission_code = "example.manage"
        permission_codes = ("example.view", "example.legacy")
    class View:
        http_method_names = ["get", "post"]
        permission_classes = [Guard]
        def get(self): pass
        def post(self): pass
        __module__ = "apps.sample.views"
    callback = type("Callback", (), {"cls": View})
    codes = ("example.view", "example.manage", "example.legacy")
    rows = classify_endpoint("example/", callback, {code: {"code": code} for code in codes})
    assert {row["permission_code"] for row in rows if row["method"] == "POST"} == set(codes)
    invalid = classify_endpoint("example/", callback, {"example.view": {"code": "example.view"}})
    assert any(row["policy"] == "catalog_declaration_missing" for row in invalid)


def test_admin_callbacks_record_framework_session_and_csrf_guards():
    rows = classify_endpoint("admin/accounts/user/", lambda request: None, {})
    assert {row["method"] for row in rows} == {"GET", "HEAD", "POST"}
    assert all(row["policy"] == "django_admin_session_staff_csrf" for row in rows)


def test_specialized_action_permission_code_is_catalogued():
    class SpecializedPermission:
        permission_code = "finance.approve"
    class SpecializedView:
        http_method_names = ["post", "options"]
        permission_classes = [SpecializedPermission]
        def post(self): pass
        __module__ = "apps.finance.views"
    rows = classify_endpoint("finance/", type("Callback", (), {"cls": SpecializedView}), {"finance.approve": {}})
    assert any(r["permission_code"] == "finance.approve" and r["policy"] == "specialized_catalog_permission" for r in rows)
    assert any(r["method"] == "OPTIONS" and r["policy"] == "framework_options_exemption" for r in rows)


def test_duplicate_permission_codes_rejected_and_real_risk_metadata_used():
    with pytest.raises(ValueError, match="Duplicate"):
        build_manifest([{"code": "a"}, {"code": "a"}], [])
    manifest = build_manifest([{"code": "products.master.freeze", "action": "master.freeze", "metadata": {"path": "/products"}, "registry_status": "active"}], [])
    p = manifest["permissions"][0]
    assert p["risk"] == "high" and p["menu_path"] == "/products" and p["lifecycle"] == "active"
