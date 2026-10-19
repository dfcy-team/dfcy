import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from billiard.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import PermissionDenied

import pytest

from apps.influencers.tiktok_dataset_checkpoint import DatasetCheckpoint
from apps.influencers import tiktok_shop_dataset as dataset


def test_pre_ads_parser_checkpoint_cannot_resume_with_new_projection(tmp_path, monkeypatch):
    from apps.influencers import tiktok_dataset_checkpoint as checkpoint_module
    current_version = checkpoint_module.PARSER_VERSION
    assert current_version == "shop-dataset-2.2"
    monkeypatch.setattr(checkpoint_module, "PARSER_VERSION", "shop-dataset-2.1")
    root = tmp_path / "synthetic-checkpoint"
    with DatasetCheckpoint(root, {"tenant": 1}) as checkpoint:
        checkpoint.save({"page": 1}, {"rows": [], "next_token": "synthetic-cursor"})
    monkeypatch.setattr(checkpoint_module, "PARSER_VERSION", current_version)
    with pytest.raises(dataset.DatasetError, match="scope_mismatch"):
        with DatasetCheckpoint(root, {"tenant": 1}, resume=True):
            pass


def test_lock_scope_hash_and_private_cursor(tmp_path):
    root = tmp_path / "export"
    with DatasetCheckpoint(root, {"tenant": 1}) as checkpoint:
        checkpoint.save({"page": 1}, {"rows": [], "next_token": "private-cursor"})
        with pytest.raises(dataset.DatasetError, match="locked"):
            with DatasetCheckpoint(root, {"tenant": 1}, resume=True):
                pass
    with pytest.raises(dataset.DatasetError, match="scope_mismatch"):
        with DatasetCheckpoint(root, {"tenant": 2}, resume=True):
            pass
    with DatasetCheckpoint(root, {"tenant": 1}, resume=True) as checkpoint:
        assert checkpoint.load({"page": 1})["next_token"] == "private-cursor"
        page = next(root.glob(".page-*.json"))
        page.write_bytes(b"tampered")
        with pytest.raises(dataset.DatasetError, match="digest_mismatch"):
            checkpoint.load({"page": 1})


def test_orphan_is_not_trusted_and_can_be_repaired(tmp_path):
    root = tmp_path / "export"
    with DatasetCheckpoint(root, {"tenant": 1}) as checkpoint:
        key = checkpoint.key({"page": 1})
        (root / (".page-" + key + ".json")).write_bytes(b"orphan")
    with DatasetCheckpoint(root, {"tenant": 1}, resume=True) as checkpoint:
        assert checkpoint.load({"page": 1}) is None
        checkpoint.save({"page": 1}, {"rows": []})
        assert checkpoint.load({"page": 1}) == {"rows": []}


def make_client(auth, pages):
    client = dataset.TikTokDatasetClient(SimpleNamespace(platform_config={}), auth, http_client=Mock(), custody=Mock())
    client._request = Mock(side_effect=[{"data": page} if isinstance(page, dict) else page for page in pages])
    return client


def test_resume_verified_page_retries_failed_page(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset.retry_time, "sleep", lambda _: None)
    auth = SimpleNamespace(store_id=1, shop_cipher="secret-cipher")
    descriptor = {"query": "window"}
    with DatasetCheckpoint(tmp_path / "export", descriptor) as checkpoint:
        client = make_client(auth, [{"videos": [{"id": "one"}], "next_page_token": "private-cursor"},
                                    ConnectionError(), ConnectionError(), ConnectionError()])
        with pytest.raises(ConnectionError):
            client.collect_pages("/demo", "videos", query={}, project=lambda v: dataset.project_video(v, "2026-10-02"),
                                 staging=True, checkpoint=checkpoint)
        assert client._request.call_count == 4
    with DatasetCheckpoint(tmp_path / "export", descriptor, resume=True) as checkpoint:
        client = make_client(auth, [{"videos": [{"id": "two"}], "total_count": 3}])
        rows, pages = client.collect_pages("/demo", "videos", query={}, project=lambda v: dataset.project_video(v, "2026-10-02"),
                                         staging=True, checkpoint=checkpoint)
        assert len(rows) == 2 and pages == 2
        assert client._request.call_count == 1
        assert client.last_page_summary["status"] == "partial"
        assert client.last_page_summary["expected_count"] == 3
        assert "secret-cipher" not in "".join(p.read_text() for p in checkpoint.root.glob("*.json"))


def test_staging_manifest_days_partial_and_resume(tmp_path):
    auth = SimpleNamespace(pk=7, store_id=1, platform_store_id="shop", scopes=["data.shop_analytics.public.read"],
                           shop_cipher="secret-cipher", integration_config=SimpleNamespace(pk=8),
                           store=SimpleNamespace(code="DEMO", timezone="Asia/Manila"))
    clients = []

    def factory(*_):
        client = make_client(auth, [{"videos": [{"id": "one"}], "total_count": 2}, {"videos": [], "total_count": 0}])
        client.verify_shop = Mock()
        clients.append(client)
        return client

    kwargs = dict(output_dir=tmp_path / "export", actor=SimpleNamespace(tenant_id=1), authorizations=[auth],
                  start_date="2026-10-02", end_date="2026-10-03", creator_seeds=[], staging=True, client_factory=factory)
    manifest, _ = dataset.export_artifact(**kwargs)
    assert manifest["schema_version"] == 2 and manifest["created_at"]
    assert len(manifest["components"]) == 3
    videos = next(c for c in manifest["components"] if c["kind"] == "videos")
    assert videos["status"] == "partial" and videos["row_count"] == 1
    assert [d["status"] for d in videos["days"]] == ["partial", "complete"]
    assert all(len(c["days"]) == 2 for c in manifest["components"])
    content = (tmp_path / "export" / "manifest.json").read_bytes()
    loaded, rows = dataset.load_artifact(tmp_path / "export" / "manifest.json", dataset.digest_bytes(content))
    assert loaded == manifest and len(rows) == 1
    assert json.loads((tmp_path / "export" / videos["file"]).read_text())["payload"]["metric_date"] == "2026-10-02"
    dataset.export_artifact(**kwargs, resume=True)
    assert clients[-1]._request.call_count == 0
    with pytest.raises(FileExistsError):
        dataset.export_artifact(**kwargs)
    auth.integration_config.pk = 9
    with pytest.raises(dataset.DatasetError, match="scope_mismatch"):
        dataset.export_artifact(**kwargs, resume=True)
    assert clients[-1]._request.call_count == 0


@pytest.mark.parametrize("values", [[{"id": "one"}, {"id": "one"}], [{}], [{"id": "one", "video_id": "two"}]])
def test_bad_identity_never_partial(values):
    client = make_client(SimpleNamespace(shop_cipher="demo"), [{"videos": values, "total_count": 100}])
    with pytest.raises(dataset.DatasetError):
        client.collect_pages("/demo", "videos", query={}, project=lambda v: dataset.project_video(v, "2026-10-02"), staging=True)


def test_enrichment_whitelist_zero_and_missing(monkeypatch):
    auth = SimpleNamespace(store_id=1, shop_cipher="demo", scopes=["seller.order.info"])
    client = make_client(auth, [{"orders": [{"id": "one", "buyer_email": "private",
        "payment": {"total_amount": "12.5", "currency": "PHP"},
        "line_items": [{"sku_id": "sku", "sale_price": "8"}]}]}])
    client.preflight = Mock()
    client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)
    rows = [dataset.project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product", "price": {"amount": "0"}}),
            dataset.project_order({"id": "missing"}, {"sku_id": "sku", "product_id": "product"})]
    client.enrich_orders(rows)
    assert rows[0]["price"]["amount"] == "0"
    assert rows[0]["order_payment"]["amount"] == "12.5"
    assert rows[1]["order_payment"]["amount"] is None
    assert rows[1]["order_payment"]["status"] == "missing"
    assert "private" not in json.dumps(rows)


def test_corrupted_detail_checkpoint_cannot_publish_complete_empty_orders(tmp_path):
    auth = SimpleNamespace(pk=7, store_id=1, platform_store_id="shop", scopes=[], shop_cipher="demo",
        integration_config=SimpleNamespace(pk=8), store=SimpleNamespace(code="DEMO", timezone="Asia/Manila"))
    client = Mock(request_count=0)
    client.affiliate_orders.return_value = ([dataset.project_order(
        {"id": "order-one", "create_time": 1790899200}, {"sku_id": "sku", "product_id": "product"})], 1)
    client.last_page_summary = dict(status="complete", reason="pagination_exhausted", expected_count=1,
        observed_count=1, page_count=1, pagination_exhausted=True)
    client.enrich_orders.side_effect = dataset.DatasetError("checkpoint_page_digest_mismatch")
    client.video_day.side_effect = dataset.DatasetError("scope_not_authorized")
    manifest, digest = dataset.export_artifact(output_dir=tmp_path / "export", actor=SimpleNamespace(tenant_id=1),
        authorizations=[auth], start_date="2026-10-02", end_date="2026-10-02", creator_seeds=[],
        staging=True, enrich_orders=True, client_factory=lambda *_: client)
    component = next(c for c in manifest["components"] if c["kind"] == "affiliate_orders")
    assert component["status"] == "failed" and "file" not in component
    assert component["days"][0]["status"] == "failed"
    assert component["days"][0]["observed_count"] == 0
    assert component["days"][0]["reason"] == "checkpoint_page_digest_mismatch"
    _, rows = dataset.load_artifact(tmp_path / "export" / "manifest.json", digest)
    assert not any(row["kind"] == "affiliate_orders" for row in rows)


def test_loader_rejects_affiliate_day_count_disagreement(tmp_path):
    manifest = dict(schema_version=2, tenant_id=1, start_date="2026-10-02", end_date="2026-10-02",
        stores=[dict(store_id=1, store_code="DEMO", timezone="Asia/Manila")], components=[])
    for kind in sorted(dataset.KINDS):
        filename = kind + ".jsonl"
        (tmp_path / filename).write_bytes(b"")
        manifest["components"].append(dict(store_id=1, kind=kind, status="complete", row_count=0,
            file=filename, sha256=dataset.digest_bytes(b""), days=[dict(date="2026-10-02", status="complete",
                reason="pagination_exhausted", expected_count=0, observed_count=0, page_count=1,
                pagination_exhausted=True)]))
    affiliate = next(c for c in manifest["components"] if c["kind"] == "affiliate_orders")
    affiliate["days"][0].update(expected_count=1, observed_count=1)
    content = dataset.canonical_bytes(manifest)
    path = tmp_path / "manifest.json"
    path.write_bytes(content)
    with pytest.raises(dataset.DatasetError, match="day_observation_count_mismatch"):
        dataset.load_artifact(path, dataset.digest_bytes(content))


def test_only_transport_errors_retry(monkeypatch):
    monkeypatch.setattr(dataset.retry_time, "sleep", lambda _: None)
    client = make_client(SimpleNamespace(shop_cipher="demo"), [dataset.DatasetError("provider_36009002")])
    with pytest.raises(dataset.DatasetError):
        client.collect_pages("/demo", "videos", query={}, project=lambda v: v, staging=True)
    assert client._request.call_count == 1


@pytest.mark.parametrize("amount,status", [("", "missing"), (None, "missing"), ("0", "matched")])
def test_empty_payment_missing_explicit_zero_matched(amount, status):
    auth = SimpleNamespace(store_id=1, shop_cipher="demo", scopes=["seller.order.info"])
    client = make_client(auth, [{"orders": [{"id": "one", "payment": {"total_amount": amount, "currency": "PHP"},
                                            "line_items": [{"sku_id": "sku", "sale_price": "2"}]}]}])
    client.preflight = Mock()
    client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)
    rows = [dataset.project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product"})]
    client.enrich_orders(rows)
    assert rows[0]["order_payment"]["status"] == status
    assert rows[0]["order_payment"]["amount"] == ("0" if amount == "0" else None)
    assert rows[0]["price"]["amount"] == "2"
    assert rows[0]["product_price_source"] == "ordinary_order_detail"


def test_missing_enrichment_scope_never_requests_and_preserves_null():
    client = make_client(SimpleNamespace(store_id=1, shop_cipher="demo", scopes=[]), [])
    rows = [dataset.project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product"})]
    client.enrich_orders(rows)
    assert client._request.call_count == 0
    assert rows[0]["order_payment"] == {"amount": None, "currency": None, "status": "missing", "source": "ordinary_order_detail"}


def test_stale_lock_not_reclaimed(tmp_path):
    root = tmp_path / "export"
    with DatasetCheckpoint(root, {}) as checkpoint:
        pass
    (root / ".lock").write_text("stale")
    with pytest.raises(dataset.DatasetError, match="locked"):
        with DatasetCheckpoint(root, {}, resume=True):
            pass
    assert (root / ".lock").read_text() == "stale"


def test_checkpoint_size_cap(tmp_path, monkeypatch):
    from apps.influencers import tiktok_dataset_checkpoint as journal
    with DatasetCheckpoint(tmp_path / "export", {}) as checkpoint:
        monkeypatch.setattr(journal, "MAX_ARTIFACT_BYTES", 128)
        with pytest.raises(dataset.DatasetError, match="artifact_size_exceeded"):
            checkpoint.save({}, {"rows": ["x" * 200]})


def test_malformed_day_forces_failed_component_not_partial(tmp_path):
    auth = SimpleNamespace(pk=7, store_id=1, platform_store_id="shop", scopes=["data.shop_analytics.public.read"],
                           shop_cipher="demo", integration_config=SimpleNamespace(pk=8),
                           store=SimpleNamespace(code="DEMO", timezone="Asia/Manila"))

    def factory(*_):
        client = make_client(auth, [{"videos": [{"id": "one"}, {"id": "one"}], "total_count": 100},
                                   {"videos": [{"id": "two"}], "total_count": 1}])
        client.verify_shop = Mock()
        return client

    manifest, digest = dataset.export_artifact(output_dir=tmp_path / "export", actor=SimpleNamespace(tenant_id=1),
        authorizations=[auth], start_date="2026-10-02", end_date="2026-10-03", creator_seeds=[], staging=True, client_factory=factory)
    videos = next(c for c in manifest["components"] if c["kind"] == "videos")
    assert videos["status"] == "failed" and "file" not in videos
    assert all(d["status"] == "failed" and d["observed_count"] == 0 for d in videos["days"])
    _, rows = dataset.load_artifact(tmp_path / "export" / "manifest.json", digest)
    assert rows == []


def test_v2_loader_requires_all_window_days(tmp_path):
    from tests.test_tiktok_shop_dataset import artifact
    path, _ = artifact(tmp_path)
    manifest = json.loads(path.read_bytes())
    manifest["schema_version"] = 2
    for component in manifest["components"]:
        component["days"] = []
    content = dataset.canonical_bytes(manifest)
    path.write_bytes(content)
    with pytest.raises(dataset.DatasetError, match="day_set_incomplete"):
        dataset.load_artifact(path, dataset.digest_bytes(content))


@pytest.mark.parametrize("error", [TimeoutError, SoftTimeLimitExceeded])
@pytest.mark.parametrize("location", ["preflight", "detail"])
def test_enrichment_cancellation_always_propagates(error, location):
    client = make_client(SimpleNamespace(store_id=1, shop_cipher="demo", scopes=["seller.order.info"]), [error()])
    client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)
    client.preflight = Mock(side_effect=error() if location == "preflight" else None)
    rows = [dataset.project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product"})]
    with pytest.raises(error):
        client.enrich_orders(rows)
    assert client._request.call_count == (0 if location == "preflight" else 1)
    assert "order_payment" not in rows[0]


@pytest.mark.parametrize("error", [PermissionDenied("denied"), dataset.DatasetError("scope_not_authorized"),
                                   RuntimeError("credential_unavailable")])
def test_permanent_enrichment_failures_not_retried(error):
    client = make_client(SimpleNamespace(store_id=1, shop_cipher="demo", scopes=["seller.order.info"]), [error])
    client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)
    client.preflight = Mock()
    rows = [dataset.project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product"})]
    client.enrich_orders(rows)
    assert client._request.call_count == 1
    assert rows[0]["order_payment"]["status"] == "missing"


@pytest.mark.parametrize("error", [TimeoutError, SoftTimeLimitExceeded])
@pytest.mark.parametrize("location", ["identity", "video", "enrichment"])
def test_staging_export_cancellation_does_not_publish_manifest(tmp_path, error, location):
    auth = SimpleNamespace(pk=7, store_id=1, platform_store_id="shop", scopes=[], shop_cipher="demo",
                           integration_config=SimpleNamespace(pk=8), store=SimpleNamespace(code="DEMO", timezone="Asia/Manila"))
    client = Mock(request_count=0)
    client.verify_shop.side_effect = error() if location == "identity" else None
    client.affiliate_orders.return_value = ([], 1)
    client.last_page_summary = {"status": "complete", "reason": "pagination_exhausted", "expected_count": 0,
                               "observed_count": 0, "page_count": 1, "pagination_exhausted": True}
    client.enrich_orders.side_effect = error() if location == "enrichment" else None
    client.video_day.side_effect = error() if location == "video" else None
    with pytest.raises(error):
        dataset.export_artifact(output_dir=tmp_path / "export", actor=SimpleNamespace(tenant_id=1), authorizations=[auth],
            start_date="2026-10-02", end_date="2026-10-02", creator_seeds=[], staging=True,
            enrich_orders=True, client_factory=lambda *_: client)
    assert not (tmp_path / "export" / "manifest.json").exists()
    assert not (tmp_path / "export" / ".lock").exists()


@pytest.mark.parametrize("all_videos_failed", [False, True])
def test_schema2_export_to_real_staging_projection_no_database(tmp_path, monkeypatch, all_videos_failed):
    from apps.influencers import tiktok_dataset_staging as staging
    from apps.influencers import tiktok_dataset_import as importer

    store = SimpleNamespace(pk=1, tenant_id=1, code="DEMO", external_store_id="shop", timezone="Asia/Manila",
                            currency="PHP", country_code="PH", platform=SimpleNamespace(platform_type="tiktok", code="tiktok"))
    auth = SimpleNamespace(pk=7, store_id=1, platform_store_id="shop", shop_cipher="demo", store=store,
        integration_config=SimpleNamespace(pk=8), scopes=["seller.affiliate_collaboration.read", "seller.order.info",
            "data.shop_analytics.public.read", "seller.creator_marketplace.read"])
    monkeypatch.setattr(dataset, "get_runtime_platform_config", lambda _: {"affiliate_seller_creator_read_approved": True})
    monkeypatch.setattr(importer.StoreMaster.objects, "select_related",
                        Mock(return_value=SimpleNamespace(filter=Mock(return_value=[store]))))
    profile = SimpleNamespace(influencer_id=9, is_active=True, influencer=SimpleNamespace(platform="tiktok", handle="demo"))
    monkeypatch.setattr(staging.InfluencerProfile.objects, "filter",
                        Mock(return_value=SimpleNamespace(select_related=Mock(return_value=[profile]))))

    def factory(*_):
        client = make_client(auth, [])
        client.verify_shop = Mock()
        client.preflight = Mock()
        client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)

        def request(path, *, query=None, **_):
            if path == "/affiliate_seller/202410/orders/search":
                return {"data": {"orders": [{"id": "order-one", "create_time": 1790899200,
                    "buyer_email": "private@example.test", "skus": [
                        {"sku_id": "sku-one", "product_id": "product-one", "quantity": 1,
                         "price": {"amount": "0", "currency": "PHP"}},
                        {"sku_id": "sku-two", "product_id": "product-one", "quantity": 1}]}], "total_count": 1}}
            if path == client.ORDER_DETAIL_PATH:
                return {"data": {"orders": [{"id": "order-one", "payment": {"total_amount": "0", "currency": "PHP"},
                    "line_items": [{"sku_id": "sku-one", "sale_price": "8"}, {"sku_id": "sku-two", "sale_price": "2"}]}]}}
            if path.startswith("/affiliate_seller/202406/marketplace_creators/"):
                return {"data": {"creator": {"username": "demo", "nickname": "Snapshot", "selection_region": "PH"}}}
            if all_videos_failed:
                raise dataset.DatasetError("provider_36009002")
            return {"data": {"videos": [{"id": "video-one", "views": 0,
                "gmv": {"amount": "0", "currency": "PHP"}, "creator": {"author_type": "AFFILIATE"}}], "total_count": 2}}

        client._request = Mock(side_effect=request)
        return client

    manifest, digest = dataset.export_artifact(output_dir=tmp_path / "export", actor=SimpleNamespace(tenant_id=1),
        authorizations=[auth], start_date="2026-10-02", end_date="2026-10-02", creator_seeds=[("123", 9)],
        staging=True, enrich_orders=True, client_factory=factory)
    loaded, rows = dataset.load_artifact(tmp_path / "export" / "manifest.json", digest)
    start, end, _, partitions = staging._validated_manifest(loaded, rows, SimpleNamespace(pk=1), store)
    grouped = staging._prepare(rows, store=store, start=start, end=end, schema_version=2, partitions=partitions)
    candidates = {}
    for (kind, _), payloads in grouped.items():
        project = {"videos": lambda p: staging._video(p, store), "creators": lambda p: staging._creator(p, store),
                   "affiliate_orders": lambda p: staging._affiliate(p, store, start, end)}[kind]
        for payload in payloads:
            for record_kind, key, projected in project(payload):
                identity = (record_kind, dataset.canonical_bytes(key))
                if identity in candidates:
                    assert candidates[identity] == projected
                candidates[identity] = projected
    payments = [p for (kind, _), p in candidates.items() if kind == "order_payment"]
    assert len(payments) == 1 and payments[0]["amount"] == "0" and payments[0]["status"] == "matched"
    lines = [p for (kind, _), p in candidates.items() if kind == "affiliate_line"]
    assert len(lines) == 2 and {p["price"]["amount"] for p in lines} == {"0", "2"}
    assert all("payment_amount" not in p and "order_payment" not in p for p in lines)
    creators = [p for (kind, _), p in candidates.items() if kind == "creator_snapshot"]
    assert len(creators) == 1 and creators[0]["identity_status"] == "matched"
    assert "private@example.test" not in json.dumps(rows)
    quality = partitions[("videos", date(2026, 10, 2))]["quality"]
    assert quality == ("failed" if all_videos_failed else "partial")
    videos = [p for (kind, _), p in candidates.items() if kind == "video_daily"]
    if all_videos_failed:
        assert videos == []
        assert next(c for c in manifest["components"] if c["kind"] == "videos")["days"]
    else:
        assert len(videos) == 1 and videos[0]["metrics"]["views"] == 0
        assert videos[0]["metrics"]["likes"] is None
