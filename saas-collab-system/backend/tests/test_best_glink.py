import hashlib
import pytest
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.best_access import BestAccessInput
from apps.integrations.best_glink import BestGlinkClient, gateway_for


class BestGlinkTests(SimpleTestCase):
    def make_client(self, response):
        config = SimpleNamespace(platform_config={"partner_id": "TEST-P", "customer_code": "TEST-C"},
            credential_id="test-ref", environment="production", connect_timeout_seconds=3, read_timeout_seconds=8)
        auth = SimpleNamespace(external_warehouse_code="TEST-W", warehouse=SimpleNamespace(country_code="MY"))
        http, custody = Mock(), Mock()
        custody.retrieve_secret.return_value = "TEST-KEY"
        http.request.return_value = SimpleNamespace(status_code=200, text=json.dumps(response))
        client = BestGlinkClient(config, auth, http_client=http, custody=custody)
        client.preflight = Mock()
        return client, http

    def test_three_fields_are_sufficient(self):
        serializer = BestAccessInput(data={"partner_id": "TEST-P", "partner_key": "TEST-KEY",
            "customer_code": "TEST-C", "version": 0, "idempotency_key": "TEST-SAVE-001"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("gateway", serializer.validated_data)
        self.assertNotIn("warehouse_code", serializer.validated_data)

    def test_exact_json_form_and_signature(self):
        client, http = self.make_client({"success": True, "resultList": []})
        client.query("GLINK_QUERY_WAREHOUSE_NOTIFY", {})
        form = http.request.call_args.kwargs["form_body"]
        self.assertEqual(form["partnerId"], "TEST-P")
        self.assertNotIn("partnerID", form)
        self.assertEqual(json.loads(form["bizData"]), {"customerCode": "TEST-C"})
        self.assertEqual(form["sign"], hashlib.md5((form["bizData"] + "TEST-KEY").encode()).hexdigest())
        self.assertFalse(http.request.call_args.kwargs["retry"])
        self.assertEqual(http.request.call_args.args[1], gateway_for("production"))

    def test_scope_override_and_write_blocked_before_network(self):
        client, http = self.make_client({"success": True})
        for operation, fields in [("GLINK_QUERY_WAREHOUSE_NOTIFY", {"customerCode": "OTHER"}),
                                  ("GLINK_QUERY_INVENTORY_NOTIFY", {"warehouseCode": "OTHER"}),
                                  ("GLINK_CREATE_ORDER_NOTIFY", {})]:
            with self.assertRaises(PermissionDenied):
                client.query(operation, fields)
        http.request.assert_not_called()

    def test_discovery_checks_customer_and_country(self):
        client, _ = self.make_client({})
        client.query = Mock(side_effect=[{"customerDTOList": [{"customerCode": "TEST-C", "warehouseCodes": "MY-A:BEST,TH-A:BEST"}]},
            {"resultList": [{"warehouseCode": "MY-A", "country": "MY"}, {"warehouseCode": "MY-OTHER", "country": "MY"},
                            {"warehouseCode": "TH-A", "country": "TH"}]}])
        self.assertEqual(client.discover_warehouses(), [{"code": "MY-A", "name": "MY-A", "country": "MY", "time_zone": ""}, {"code": "TH-A", "name": "TH-A", "country": "TH", "time_zone": ""}])

    def test_wrong_customer_never_queries_warehouses(self):
        client, _ = self.make_client({})
        client.query = Mock(return_value={"customerDTOList": [{"customerCode": "OTHER"}]})
        with self.assertRaises(PermissionDenied):
            client.discover_warehouses()
        self.assertEqual(client.query.call_count, 1)

    def test_inventory_batches_and_scope(self):
        client, _ = self.make_client({})
        client.query = Mock(return_value={"inventoryVOList": [{"customerCode": "TEST-C", "warehouseCode": "TEST-W",
            "sku": f"SKU{i}", "skuStatus": "GOOD", "totalQty": 8 if i == 0 else 0, "salableQty": 5 if i == 0 else 0} for i in range(200)]})
        result = client.fetch_inventory(None, {"sku_codes": [f"SKU{i}" for i in range(201)]})
        self.assertEqual(result["next_cursor"], "200")
        self.assertEqual(len(client.query.call_args.args[1]["skus"]), 200)
        self.assertEqual(result["records"][0]["normalQuantity"], 5)
        self.assertEqual(result["records"][1]["totalQuantity"], 0)
        self.assertEqual(len({row["_snapshot_at_utc"] for row in result["records"]}), 1)
        self.assertIs(client.query.call_args.args[1]["ignoreZero"], False)
        client.query.return_value["inventoryVOList"][0]["warehouseCode"] = "OTHER"
        with self.assertRaises(ValidationError):
            client.fetch_inventory(None, {"sku_codes": ["SKU0"]})

    def test_missing_inventory_is_not_zero(self):
        client, _ = self.make_client({})
        client.query = Mock(return_value={})
        with self.assertRaises(ValidationError):
            client.fetch_inventory(None, {"sku_codes": ["SKU0"]})

    def test_nested_scope_override_is_rejected(self):
        client, http = self.make_client({"success": True})
        client.authorization.integration_config = client.config
        with self.assertRaises(PermissionDenied):
            client.query("GLINK_BATCH_QUERY_ORDER_NOTIFY", {"items": [{"customerCode": "OTHER"}]})
        http.request.assert_not_called()

    def test_optional_empty_detail_identity_inherits_validated_parent(self):
        from apps.integrations.best_glink import check_identity
        client, _ = self.make_client({})
        client.authorization.integration_config = client.config
        data = {"customerCode": "TEST-C", "warehouseCode": "TEST-W", "packages": [{"customerCode": None, "warehouseCode": ""}]}
        check_identity(data, client.authorization)
        data["packages"][0]["customerCode"] = "OTHER"
        with self.assertRaises(PermissionDenied):
            check_identity(data, client.authorization)
        data["customerCode"] = None
        with self.assertRaises(PermissionDenied):
            check_identity(data, client.authorization)

    def test_ecapi_operation_is_not_accepted(self):
        client, http = self.make_client({"success": True})
        with self.assertRaises(ValidationError):
            client.query("WMS_SO_LIST_QUERY", {})
        http.request.assert_not_called()


class BestGlinkBusinessTests(SimpleTestCase):
    def auth(self):
        return SimpleNamespace(external_warehouse_code="TEST-W",
            integration_config=SimpleNamespace(platform_config={"customer_code": "TEST-C"}))

    def test_package_quantities_are_not_copied_from_order(self):
        from apps.integrations.best_glink_business import packages
        data = {"customerCode": "TEST-C", "warehouseCode": "TEST-W", "orderNumber": "SO1",
            "stage": "SHIPPED", "shippingTime": "2026-11-19T09:00:00+08:00",
            "items": [{"sku": "A", "quantity": 9}], "packages": [
                {"packageNumber": "P1", "packageContents": [{"sku": "A", "quantity": 2}]},
                {"packageNumber": "P2", "packageContents": [{"sku": "A", "quantity": 7}]}]}
        result = packages(data, self.auth())
        self.assertEqual([row["items"][0]["quantity"] for row in result], [2, 7])
        self.assertEqual(result[0]["shipped_at_utc"], "2026-11-19T01:00:00+00:00")
        data["packages"][1]["packageNumber"] = "P1"
        with self.assertRaises(ValidationError):
            packages(data, self.auth())

    def test_return_requires_exact_type_identity_and_putaway(self):
        from apps.integrations.best_glink_business import return_receipt
        row = {"customerCode": "TEST-C", "warehouseCode": "TEST-W", "asnNumber": "R1",
            "asnType": "RETURN", "stage": "RECEIVED", "putawayStage": "PENDING"}
        data = {"total": 1, "asnInfoList": [row]}
        self.assertEqual(return_receipt(data, self.auth(), "R1")["lines"], [])
        row.update(putawayStage="COMPLETED", putawayTime="2026-11-19 09:00:00",
            asnLineItems=[{"sku": "A", "putawayedQuantity": 2}])
        result = return_receipt(data, self.auth(), "R1")
        self.assertIsNone(result["received_at"])
        self.assertEqual(result["lines"], [{"sku": "A", "received_quantity": 2}])
        row["asnType"] = "PURCHASE"
        with self.assertRaises(ValidationError):
            return_receipt(data, self.auth(), "R1")


def test_confirmed_china_clock_converts_only_when_explicit():
    from apps.integrations.best_glink_business import business_time
    auth = SimpleNamespace(integration_config=SimpleNamespace(platform_config={}))
    assert business_time('2026-11-19 09:00:00', auth) is None
    auth.integration_config.platform_config['business_time_zone'] = 'Asia/Shanghai'
    assert business_time('2026-11-19 09:00:00', auth) == '2026-11-19T01:00:00+00:00'
    assert business_time('2026-11-19T09:00:00+07:00', auth) == '2026-11-19T02:00:00+00:00'


def test_inbound_fact_requires_real_putaway_and_exact_line_identity():
    from apps.integrations.best_glink_business import inbound_records
    auth = SimpleNamespace(external_warehouse_code='W1', integration_config=SimpleNamespace(platform_config={
        'customer_code': 'C1', 'business_time_zone': 'Asia/Shanghai'}))
    row = {'customerCode': 'C1', 'warehouseCode': 'W1', 'asnNumber': 'ASN1', 'asnType': 'TRANSFER_AVAILABLE',
        'putawayStage': 'PENDING'}
    assert inbound_records(row, auth) == []
    row.update(putawayStage='COMPLETED', putawayTime='2026-11-19 09:00:00',
        asnLineItems=[{'lineNo': '1', 'sku': 'SKU1', 'quantity': 10, 'putawayedQuantity': 8}])
    result = inbound_records(row, auth)
    assert result[0]['inbound_type'] == 'transfer'
    assert result[0]['received_quantity'] == 8
    assert result[0]['received_at_utc'] == '2026-11-19T01:00:00+00:00'
    row['asnLineItems'].append(row['asnLineItems'][0].copy())
    with pytest.raises(ValidationError):
        inbound_records(row, auth)


@pytest.mark.django_db
def test_best_inbound_fact_persists_to_shared_model():
    from tests.test_sales_management import create_scope, create_run
    from apps.integrations.adapters import BestInboundAdapter
    from apps.integrations.best_glink_business import inbound_records
    from apps.commerce.models import InboundRecord
    tenant, _, _, warehouse = create_scope('best-inbound')
    run = create_run(tenant, 'inbound', 'best-inbound', platform='best_ecapi')
    config = run.sync_job.integration_config
    config.platform_config = {'customer_code': 'C1', 'business_time_zone': 'Asia/Shanghai'}
    config.save()
    auth = SimpleNamespace(tenant_id=tenant.pk, warehouse=warehouse, warehouse_id=warehouse.pk,
        integration_config_id=config.pk, integration_config=config, external_warehouse_code='W1')
    row = {'customerCode': 'C1', 'warehouseCode': 'W1', 'asnNumber': 'ASN1', 'asnType': 'PURCHASE',
        'putawayStage': 'COMPLETED', 'putawayTime': '2026-11-19 09:00:00',
        'asnLineItems': [{'lineNo': '1', 'sku': 'SKU1', 'quantity': 10, 'putawayedQuantity': 8}]}
    record = inbound_records(row, auth)[0]
    adapter = BestInboundAdapter(config)
    adapter.warehouse_authorization = auth
    adapter.source_run = run
    assert adapter.persist_record(run.sync_job, record)['action'] == 'created'
    assert adapter.persist_record(run.sync_job, record)['action'] == 'updated'
    fact = InboundRecord.objects.get(tenant=tenant)
    assert fact.received_quantity == 8
    assert fact.warehouse_id == warehouse.pk

def test_inbound_page_requires_complete_counts_and_confirmed_time_zone():
    client, _ = BestGlinkTests().make_client({})
    client.config.platform_config['business_time_zone'] = 'Asia/Shanghai'
    client.query = Mock(return_value={'success': True, 'total': 0, 'asnInfoList': []})
    page = client.fetch_inbound(None, {'time_from': 1795017600, 'time_to': 1795104000})
    assert page['records'] == [] and page['next_cursor'] == ''
    fields = client.query.call_args.args[1]
    assert fields['lastUpdatedTimeFrom'] < fields['lastUpdatedTimeTo']
    client.query.return_value['total'] = 2
    with pytest.raises(ValidationError):
        client.fetch_inbound(None, {'time_from': 1795017600, 'time_to': 1795104000})
    client.config.platform_config.pop('business_time_zone')
    with pytest.raises(ValidationError):
        client.fetch_inbound(None, {'time_from': 1795017600, 'time_to': 1795104000})

def test_zero_snapshot_retains_catalogue_case_and_rejects_missing_rows():
    client, _ = BestGlinkTests().make_client({})
    client.query = Mock(return_value={'inventoryVOList': [{'customerCode': 'TEST-C', 'warehouseCode': 'TEST-W',
        'sku': 'SKU-BLUE', 'skuStatus': 'GOOD', 'totalQty': 0, 'salableQty': 0}]})
    scope = {'sku_codes': ['SKU-Blue'], 'snapshot_at_utc': '2026-11-19T08:00:00+00:00'}
    record = client.fetch_inventory(None, scope)['records'][0]
    assert record['itemSkuCode'] == 'SKU-Blue'
    assert record['totalQuantity'] == 0
    assert record['_snapshot_at_utc'] == scope['snapshot_at_utc']
    client.query.return_value['inventoryVOList'] = []
    with pytest.raises(ValidationError):
        client.fetch_inventory(None, scope)
    with pytest.raises(ValidationError):
        client.fetch_inventory(None, {'sku_codes': ['SKU-Blue', 'SKU-BLUE']})
