import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.influencers import tiktok_shop_dataset as dataset


def client_with_pages(*pages):
    client = dataset.TikTokDatasetClient(SimpleNamespace(platform_config={}),
        SimpleNamespace(shop_cipher="demo-cipher"), http_client=Mock(), custody=Mock())
    client._request = Mock(side_effect=[{"code": 0, "data": page} for page in pages])
    return client


def test_missing_numbers_remain_null_and_actual_zero_is_zero():
    row = dataset.project_video({"video_id": "demo", "creator": {"open_id": "opaque-open-id", "author_type": "AFFILIATE"},
                                 "total_performance": {"views": 0, "gmv": {"amount": "0", "currency": "PHP"}}}, "2026-10-02")
    assert row["metrics"]["views"] == 0
    assert row["metrics"]["likes"] is None
    assert row["metrics"]["gmv"]["amount"] == "0"
    assert row["metrics"]["direct_gmv"]["amount"] is None
    assert row["creator_open_id"] == "opaque-open-id"
    assert "creator_id" not in row


def test_shop_video_list_id_and_flat_metrics_preserved_without_order_guessing():
    row = dataset.project_video({"id": "demo-list-id", "views": 123, "sku_orders": 2,
        "gmv": {"amount": "45.67", "currency": "PHP"}, "video_post_time": 1790899200,
        "creator": {"open_id": "opaque", "author_type": "AFFILIATE"}}, "2026-10-02")
    assert row["external_video_id"] == "demo-list-id"
    assert row["metrics"]["views"] == 123
    assert row["metrics"]["sku_orders"] == 2
    assert row["metrics"]["orders"] is None
    assert row["metrics"]["gmv"]["amount"] == "45.67"
    assert row["published_at"] == "2026-10-02T00:00:00+00:00"


def test_conflicting_video_id_aliases_fail_closed():
    with pytest.raises(dataset.DatasetError, match="conflicting_video_identifiers"):
        dataset.project_video({"id": "one", "video_id": "two"}, "2026-10-02")


def test_video_naive_source_time_preserved_without_guessed_timezone():
    row = dataset.project_video({"id": "demo", "video_post_time": "2026-10-02 14:23:01"}, "2026-10-02")
    assert row["published_at"] is None
    assert row["source_published_at"] == "2026-10-02 14:23:01"


def test_long_source_title_is_preserved_but_trial_import_quarantines_it():
    from apps.influencers.tiktok_dataset_import import _prepare_video_candidates
    title = "x" * 688
    payload = dataset.project_video({"id": "demo", "title": title,
                                    "creator": {"author_type": "AFFILIATE"}}, "2026-10-02")
    assert payload["title"] == title
    rows = [{"kind": "videos", "store_id": 8, "payload": payload}]
    candidates, quarantined = _prepare_video_candidates(rows, store_id=8,
        start_date=date(2026, 10, 2), end_date=date(2026, 10, 8))
    assert candidates == []
    assert quarantined == {"invalid_video_title": 1}


def test_source_title_operational_size_cap_still_rejects_oversize():
    with pytest.raises(dataset.DatasetError, match="oversized_text"):
        dataset.project_video({"id": "demo", "title": "x" * 8193}, "2026-10-02")


@pytest.mark.parametrize("value", ["2026-02-30 01:00:00", "2026-10-02 24:00:00", "2026-10-02T14:23:01", -1, 10**18])
def test_unverified_video_time_formats_fail_closed(value):
    with pytest.raises(dataset.DatasetError, match="invalid_video_post_time"):
        dataset.project_video({"id": "demo", "video_post_time": value}, "2026-10-02")


def test_order_projection_excludes_buyer_pii_and_does_not_invent_payment():
    row = dataset.project_order({"id": "order-demo", "create_time": 1790900000, "buyer_email": "private@example.test"},
        {"sku_id": "sku-demo", "product_id": "product-demo", "quantity": 1, "buyer_phone": "private",
         "actual_commission_base": {"amount": "23.45", "currency": "PHP"}})
    assert row["payment_amount"] is None
    assert row["fully_return"] is None
    assert "private" not in json.dumps(row)
    assert row["actual_commission_base"]["amount"] == "23.45"


@pytest.mark.parametrize("value", [None, "0", "1.2345"])
def test_ads_projection_preserves_independent_sku_amount_without_quantity(value):
    sku = {"sku_id": "synthetic-sku", "quantity": 30,
           "actual_paid_commission": {"amount": "2", "currency": "PHP"}}
    if value is not None:
        sku["actual_paid_shop_ads_commission"] = {"amount": value, "currency": "PHP"}
    row = dataset.project_order({"id": "synthetic-order"}, sku)
    assert row["actual_paid_commission"] == {"amount": "2", "currency": "PHP"}
    assert row["actual_paid_shop_ads_commission"] == {"amount": value, "currency": "PHP" if value is not None else None}
    assert row["quantity"] == 30 and row["payment_amount"] is None
    assert row["canonical_import_blocker"] == "sku_payment_semantics_not_verified"


@pytest.mark.parametrize("ads", [{"amount": "0", "currency": "MYR"}, {"amount": "2", "currency": None},
                                 {"amount": None, "currency": "MYR"}])
def test_ads_projection_rejects_missing_or_conflicting_sku_currency(ads):
    with pytest.raises(dataset.DatasetError, match="^affiliate_currency_mismatch$"):
        dataset.project_order({"id": "synthetic-order"}, {
            "sku_id": "synthetic-sku", "actual_paid_commission": {"amount": "2", "currency": "PHP"},
            "actual_paid_shop_ads_commission": ads,
        })


def test_mixed_sku_settlement_never_copies_order_level_facts():
    order = {"id": "synthetic-mixed", "create_time": 1790899200, "status": "SETTLED",
             "settlement_status": "SETTLED"}
    states = ["SETTLED", "INELIGIBLE", "To-SETTLE", None, ""]
    skus = [dict(sku_id=str(i), product_id="synthetic", **({"settlement_status": state} if state is not None else {}))
            for i, state in enumerate(states)]
    projected = [dataset.project_order(order, sku)["settlement_status"] for sku in skus]
    assert projected == ["\u5df2\u7ed3\u7b97", "\u4e0d\u7b26\u5408\u6761\u4ef6", "\u5f85\u7ed3\u7b97", None, None]
    assert "settlement_status" not in skus[3] and order["status"] == "SETTLED"


def test_unknown_sku_settlement_projection_fails_closed():
    with pytest.raises(dataset.DatasetError, match="^unknown_settlement_status$"):
        dataset.project_order({"id": "synthetic"}, {"sku_id": "synthetic", "settlement_status": "COMPLETED"})


@pytest.mark.parametrize("code", [None, False, True, "unknown", 36009002])
def test_explicit_provider_success_required(code):
    client = client_with_pages()
    response = Mock()
    response.json.return_value = {"data": {}, **({"code": code} if code is not None else {})}
    with pytest.raises(dataset.DatasetError):
        client._response_json(response)


def test_repeated_page_token_fails_not_zero_or_partial_success():
    client = client_with_pages({"videos": [{"video_id": "one"}], "next_page_token": "same"},
                              {"videos": [{"video_id": "two"}], "next_page_token": "same"})
    with pytest.raises(dataset.DatasetError, match="not_advancing"):
        client.collect_pages("/demo", "videos", query={}, project=lambda row: {"external_video_id": row["video_id"]})


def test_count_mismatch_fails():
    client = client_with_pages({"videos": [], "total_count": 1})
    with pytest.raises(dataset.DatasetError, match="total_mismatch"):
        client.collect_pages("/demo", "videos", query={}, project=lambda row: row)


def test_duplicate_video_id_fails():
    client = client_with_pages({"videos": [{"video_id": "one"}, {"video_id": "one"}]})
    with pytest.raises(dataset.DatasetError, match="duplicate_page_identity"):
        client.collect_pages("/demo", "videos", query={}, project=lambda row: {"external_video_id": row["video_id"]})


def test_daily_video_window_is_exclusive_and_scope_checked():
    client = client_with_pages({"videos": []})
    client.authorization.scopes = ["data.shop_analytics.public.read"]
    client.video_day(date(2026, 10, 2))
    query = client._request.call_args.kwargs["query"]
    assert query["start_date_ge"] == "2026-10-02"
    assert query["end_date_lt"] == "2026-10-03"
    client.authorization.scopes = []
    with pytest.raises(dataset.DatasetError, match="scope_not_authorized"):
        client.video_day(date(2026, 10, 2))


def test_affiliate_total_counts_skus_not_orders():
    client = client_with_pages({"orders": [{"id": "order-one", "create_time": 1790899200, "skus": [
        {"sku_id": "sku-one", "product_id": "product-one"},
        {"sku_id": "sku-two", "product_id": "product-two"}]}], "total_count": 2})
    client.authorization.scopes = ["seller.affiliate_collaboration.read"]
    rows, pages = client.affiliate_orders(date(2026, 10, 2), date(2026, 10, 8), dataset.ZoneInfo("Asia/Manila"))
    assert len(rows) == 2 and pages == 1


def test_affiliate_total_can_count_orders_without_inventing_a_sku_unit():
    client = client_with_pages({"orders": [{"id": "order-one", "create_time": 1790899200, "skus": [
        {"sku_id": "sku-one", "product_id": "product-one"},
        {"sku_id": "sku-two", "product_id": "product-two"}]}], "total_count": 1})
    client.authorization.scopes = ["seller.affiliate_collaboration.read"]
    rows, pages = client.affiliate_orders(date(2026, 10, 2), date(2026, 10, 8), dataset.ZoneInfo("Asia/Manila"))
    assert len(rows) == 2 and pages == 1


def test_outside_window_affiliate_row_rejected():
    client = client_with_pages({"orders": [{"id": "order-one", "create_time": 1,
        "skus": [{"sku_id": "sku-one", "product_id": "product-one"}]}]})
    client.authorization.scopes = ["seller.affiliate_collaboration.read"]
    with pytest.raises(dataset.DatasetError, match="outside_verified_window"):
        client.affiliate_orders(date(2026, 10, 2), date(2026, 10, 8), dataset.ZoneInfo("Asia/Manila"))


def test_export_failure_does_not_save_provider_secret_message(tmp_path):
    class FailedClient:
        def __init__(self, *args):
            pass
        def verify_shop(self):
            raise RuntimeError("signed-url-secret-private")
    actor = SimpleNamespace(tenant_id=1)
    auth = SimpleNamespace(store_id=23, platform_store_id="shop-demo", integration_config=None,
        store=SimpleNamespace(code="DEMO", timezone="Asia/Manila"))
    manifest, digest = dataset.export_artifact(output_dir=tmp_path / "export", actor=actor, authorizations=[auth],
        start_date="2026-10-02", end_date="2026-10-08", creator_seeds=[], client_factory=FailedClient)
    assert all(component["status"] == "failed" for component in manifest["components"])
    assert "secret-private" not in json.dumps(manifest)
    loaded, rows = dataset.load_artifact(tmp_path / "export" / "manifest.json", digest)
    assert rows == [] and loaded["components"] == manifest["components"]


def artifact(tmp_path, *, bad_tenant=False):
    row = {"kind": "videos", "tenant_id": 2 if bad_tenant else 1, "store_id": 23, "store_code": "DEMO",
           "payload": {"metric_date": "2026-10-02"}}
    data = dataset.canonical_bytes(row) + b"\n"
    (tmp_path / "videos.jsonl").write_bytes(data)
    manifest = {"schema_version": 1, "tenant_id": 1, "start_date": "2026-10-02", "end_date": "2026-10-08",
                "stores": [{"store_id": 23, "store_code": "DEMO"}], "components": [
                    {"kind": "videos", "store_id": 23, "status": "complete", "file": "videos.jsonl", "sha256": dataset.digest_bytes(data), "row_count": 1},
                    {"kind": "creators", "store_id": 23, "status": "failed"},
                    {"kind": "affiliate_orders", "store_id": 23, "status": "failed"}]}
    content = dataset.canonical_bytes(manifest)
    path = tmp_path / "manifest.json"
    path.write_bytes(content)
    return path, dataset.digest_bytes(content)


def test_manifest_roundtrip_and_tamper(tmp_path):
    path, digest = artifact(tmp_path)
    manifest, rows = dataset.load_artifact(path, digest)
    assert len(rows) == 1
    (tmp_path / "videos.jsonl").write_bytes(b"tampered")
    with pytest.raises(dataset.DatasetError, match="component_digest"):
        dataset.load_artifact(path, digest)


def test_cross_tenant_artifact_rejected(tmp_path):
    path, digest = artifact(tmp_path, bad_tenant=True)
    with pytest.raises(dataset.DatasetError, match="boundary"):
        dataset.load_artifact(path, digest)


def test_unsafe_component_path_rejected(tmp_path):
    path, _ = artifact(tmp_path)
    manifest = json.loads(path.read_bytes())
    manifest["components"][0]["file"] = "../outside.jsonl"
    content = dataset.canonical_bytes(manifest)
    path.write_bytes(content)
    with pytest.raises(dataset.DatasetError, match="unsafe_component_path"):
        dataset.load_artifact(path, dataset.digest_bytes(content))


@pytest.mark.parametrize("value", [float("nan"), -1, True, "Infinity"])
def test_invalid_number_rejected(value):
    with pytest.raises(dataset.DatasetError):
        dataset._number(value)


def test_staging_video_count_mismatch_preserves_projected_rows():
    client = client_with_pages({"videos": [{"id": "one", "buyer_email": "private"}], "total_count": 10})
    client.authorization.scopes = ["data.shop_analytics.public.read"]
    rows, pages = client.video_day(date(2026, 10, 2), staging=True)
    assert len(rows) == 1 and pages == 1
    assert client.last_page_summary == {"status": "partial", "reason": "pagination_total_mismatch",
        "expected_count": 10, "observed_count": 1, "page_count": 1, "pagination_exhausted": True}
    assert "private" not in json.dumps(rows)


def test_resume_requires_explicit_staging_before_directory_creation(tmp_path):
    with pytest.raises(dataset.DatasetError, match="staging_required"):
        dataset.export_artifact(output_dir=tmp_path / "export", actor=None, authorizations=[],
            start_date="2026-10-02", end_date="2026-10-03", creator_seeds=[], resume=True)
    assert not (tmp_path / "export").exists()
