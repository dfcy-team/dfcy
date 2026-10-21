import base64
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase

from apps.commerce.models import (
    InventorySnapshot,
    RefundReturn,
    RefundReturnItem,
    SalesOrder,
    SalesOrderItem,
)
from apps.integrations.internal_readonly_api import READY
from apps.integrations.models import (
    InternalAPIClient,
    PlatformIntegrationConfig,
    ShopeeAdvertisingRecord,
    SyncJob,
    SyncRun,
)
from apps.integrations.readonly_domains import CONTRACTS
from apps.integrations.serializers import INTERNAL_API_RESOURCE_FIELDS
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


class FourDomainReadonlyEndpointTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="READONLY1", name="Readonly tenant")
        self.other_tenant = Tenant.objects.create(code="READONLY2", name="Other tenant")
        self.user = get_user_model().objects.create_user(
            username="readonly-endpoint-owner", tenant=self.tenant,
            user_type="internal", is_active=True,
        )
        self.secret = "test-secret"
        self.resources = {
            code: sorted(INTERNAL_API_RESOURCE_FIELDS[code])
            for code in CONTRACTS
        }
        self.client_obj = InternalAPIClient.objects.create(
            tenant=self.tenant, created_by=self.user, updated_by=self.user,
            name="Readonly endpoint test", caller_type="internal_system",
            client_id="readonly-endpoint-test", secret_hash=make_password(self.secret),
            secret_prefix="test", secret_fingerprint="a" * 64,
            resources=self.resources, allowed_cidrs=["10.11.0.0/16"],
            rate_limit_per_minute=500, page_size_limit=100, status="active",
            approval_status="approved",
        )
        credential = base64.b64encode(f"{self.client_obj.client_id}:{self.secret}".encode()).decode()
        self.headers = {
            "HTTP_AUTHORIZATION": f"Basic {credential}",
            "REMOTE_ADDR": "10.11.1.2",
        }
        self.base_url = "/api/internal-readonly/v1/"
        self.platform = PlatformMaster.objects.create(
            tenant=self.tenant, code="readonly-shopee", name="Shopee", platform_type="shopee",
        )
        self.store = StoreMaster.objects.create(
            tenant=self.tenant, platform=self.platform, code="readonly-store",
            name="Readonly store", country_code="PH", currency="PHP", timezone="Asia/Manila",
        )
        self.warehouse = WarehouseMaster.objects.create(
            tenant=self.tenant, code="readonly-warehouse", name="Readonly warehouse",
            country_code="PH", warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        )
        self.now = datetime(2026, 10, 1, 12, tzinfo=UTC)

    def create_run(self, resource_type, name):
        config = PlatformIntegrationConfig.objects.create(
            tenant=self.tenant,
            platform="jifeng_wms" if resource_type == "inventory_snapshot" else "shopee",
            account_alias=f"readonly-{name}",
            created_by=self.user,
        )
        job = SyncJob.objects.create(
            tenant=self.tenant, integration_config=config, resource_type=resource_type,
        )
        return config, SyncRun.objects.create(
            tenant=self.tenant, sync_job=job, run_id=f"readonly-{name}",
            idempotency_key=f"readonly-{name}",
        )

    def create_order(self, run, config, external_id, *, status="completed", currency="PHP", amount="10.0000", day=None):
        return SalesOrder.objects.create(
            tenant=self.tenant, platform=self.platform, store=self.store,
            authorization=config, source_run=run, external_order_id=external_id,
            region="PH", raw_status=status.upper(), normalized_status=status,
            status_mapping_version="1.0", created_at_utc=self.now, updated_at_utc=self.now,
            business_date=day or date(2026, 10, 1), currency=currency,
            subtotal_amount=Decimal(amount), order_total_amount=Decimal(amount),
            payload_hash="b" * 64,
        )

    def get_items(self, resource, query=""):
        response = self.client.get(f"{self.base_url}{resource}/{query}", **self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]["items"]

    def test_sales_orders_returns_lines_and_currency_cancelled_aggregates_and_having_cursor(self):
        config, run = self.create_run("sales_order", "sales")
        first = self.create_order(run, config, "order-1", amount="10.1234")
        second = self.create_order(run, config, "order-2", amount="20.0001")
        self.create_order(run, config, "order-cancelled", status="cancelled", amount="900.0000")
        self.create_order(run, config, "order-usd", currency="USD", amount="5.5555")

        items = self.get_items("sales_orders")
        self.assertEqual({row["id"] for row in items}, {first.pk, second.pk, first.pk + 2, first.pk + 3})
        self.assertEqual(set(items[0]), set(CONTRACTS["sales_orders"][1]))

        lines = SalesOrderItem.objects.create(
            sales_order=first, external_line_id="line-1", platform_product_id="product-1",
            platform_variant_id="variant-1", seller_sku="SKU-1", item_name_snapshot="Widget",
            quantity=2, original_unit_price="6.0000", sale_unit_price="5.5000",
            discount_amount="0.8766", tax_amount="0.0000", line_total_amount="10.1234", currency="PHP",
        )
        line_response = self.get_items("sales_order_items")
        self.assertEqual([row["id"] for row in line_response], [lines.pk])
        self.assertEqual(line_response[0]["line_total_amount"], "10.1234")

        _, return_run = self.create_run("refund_return", "return")
        refund = RefundReturn.objects.create(
            tenant=self.tenant, platform=self.platform, store=self.store, sales_order=first,
            source_run=return_run, external_return_id="return-1", external_refund_id="refund-1",
            case_type="refund", raw_status="COMPLETED", normalized_status="completed",
            arbitration_status="none", reason_code="changed_mind", requested_at_utc=self.now,
            updated_at_utc=self.now, completed_at_utc=self.now, currency="PHP",
            refund_amount="1.2345", refund_subtotal="1.0000", refund_shipping_fee="0.2000",
            refund_tax="0.0345", payload_hash="c" * 64,
        )
        return_line = RefundReturnItem.objects.create(
            refund_return=refund, sales_order_item=lines, external_return_item_id="return-line-1",
            external_order_item_id="line-1", seller_sku="SKU-1", quantity=1,
            currency="PHP", refund_amount="1.2345",
        )
        foreign_spu = ProductSPU.objects.create(
            tenant=self.other_tenant, spu_code="FOREIGN-SPU", product_name="Foreign widget",
        )
        foreign_sku = ProductSKU.objects.create(
            tenant=self.other_tenant, spu=foreign_spu, sku_code="FOREIGN-SKU",
        )
        # Start with valid rows, then emulate corrupt historical FK values by
        # issuing parameterized UPDATEs below model validation. The endpoint must
        # exclude the foreign SKU line from detail/rollup and the bad return link.
        malformed_line = SalesOrderItem.objects.create(
            sales_order=first, external_line_id="bad-foreign-sku-line",
            platform_product_id="foreign-product", seller_sku="FOREIGN-SKU", quantity=1,
            original_unit_price="8.0000", sale_unit_price="8.0000", line_total_amount="8.0000",
            currency="PHP",
        )
        malformed_return_line = RefundReturnItem.objects.create(
            refund_return=refund, sales_order_item=lines,
            external_return_item_id="bad-foreign-order-line", quantity=1,
            currency="PHP", refund_amount="8.0000",
        )
        with connection.cursor() as cursor:
            order_item_table = connection.ops.quote_name(SalesOrderItem._meta.db_table)
            item_sku_column = connection.ops.quote_name(SalesOrderItem._meta.get_field("internal_sku").column)
            item_pk_column = connection.ops.quote_name(SalesOrderItem._meta.pk.column)
            cursor.execute(
                f"UPDATE {order_item_table} SET {item_sku_column} = %s WHERE {item_pk_column} = %s",
                [foreign_sku.pk, malformed_line.pk],
            )
            return_item_table = connection.ops.quote_name(RefundReturnItem._meta.db_table)
            return_order_item_column = connection.ops.quote_name(RefundReturnItem._meta.get_field("sales_order_item").column)
            return_pk_column = connection.ops.quote_name(RefundReturnItem._meta.pk.column)
            cursor.execute(
                f"UPDATE {return_item_table} SET {return_order_item_column} = %s WHERE {return_pk_column} = %s",
                [malformed_line.pk, malformed_return_line.pk],
            )
        self.assertEqual(self.get_items("sales_returns")[0]["id"], refund.pk)
        return_items = self.get_items("sales_return_items")
        self.assertEqual(return_items[0]["id"], return_line.pk)
        self.assertNotIn(malformed_return_line.pk, [row["id"] for row in return_items])
        self.assertEqual(return_items[0]["refund_amount"], "1.2345")
        sku_sales = self.get_items("sku_sales")
        self.assertEqual(len(sku_sales), 1)
        self.assertEqual(sku_sales[0]["seller_sku"], "SKU-1")

        aggregates = self.client.get(self.base_url + "sales_overview/", **self.headers)
        self.assertEqual(aggregates.status_code, 200, aggregates.content)
        groups = aggregates.json()["data"]["items"]
        php = next(row for row in groups if row["currency"] == "PHP")
        usd = next(row for row in groups if row["currency"] == "USD")
        self.assertEqual(php["order_count"], 2)
        self.assertEqual(Decimal(php["order_total_amount"]), Decimal("30.1235"))
        self.assertEqual(usd["order_count"], 1)
        self.assertEqual(Decimal(usd["order_total_amount"]), Decimal("5.5555"))
        # Aggregate IDs are MIN(order.id); the collection cursor must filter grouped rows.
        one_page = self.client.get(self.base_url + "store_sales/?limit=1", **self.headers)
        self.assertEqual(one_page.status_code, 200, one_page.content)
        page = one_page.json()["data"]
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_cursor"], min(first.pk, first.pk + 3))
        next_page = self.client.get(
            self.base_url + f"store_sales/?limit=1&cursor={page['next_cursor']}", **self.headers,
        )
        self.assertEqual(next_page.status_code, 200, next_page.content)
        self.assertEqual(len(next_page.json()["data"]["items"]), 1)
        self.assertEqual(next_page.json()["data"]["items"][0]["currency"], "USD" if php["id"] < usd["id"] else "PHP")

    def test_inventory_workbench_selects_latest_before_cursor_and_hides_foreign_tenant(self):
        _, run = self.create_run("inventory_snapshot", "inventory")
        old = InventorySnapshot.objects.create(
            tenant=self.tenant, warehouse=self.warehouse, source_run=run, site_code="PH",
            source_sku="SKU-1", snapshot_at_utc=self.now, available_qty=4, on_hand_qty=7,
            provided_quantity_fields=["available_qty", "on_hand_qty"], payload_hash="d" * 64,
        )
        latest = InventorySnapshot.objects.create(
            tenant=self.tenant, warehouse=self.warehouse, source_run=run, site_code="PH",
            source_sku="SKU-1", snapshot_at_utc=self.now + timedelta(hours=1),
            available_qty=2, on_hand_qty=5, provided_quantity_fields=["available_qty"],
            payload_hash="e" * 64,
        )
        other_platform = PlatformMaster.objects.create(
            tenant=self.other_tenant, code="readonly-other", name="Shopee", platform_type="shopee",
        )
        other_warehouse = WarehouseMaster.objects.create(
            tenant=self.other_tenant, code="readonly-other-wh", name="Other warehouse",
            country_code="PH", warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        )
        foreign_user = get_user_model().objects.create_user(
            username="readonly-foreign", tenant=self.other_tenant, user_type="internal",
        )
        foreign_config = PlatformIntegrationConfig.objects.create(
            tenant=self.other_tenant, platform="jifeng_wms", account_alias="readonly-foreign",
            created_by=foreign_user,
        )
        foreign_job = SyncJob.objects.create(
            tenant=self.other_tenant, integration_config=foreign_config, resource_type="inventory_snapshot",
        )
        foreign_run = SyncRun.objects.create(
            tenant=self.other_tenant, sync_job=foreign_job, run_id="readonly-foreign",
            idempotency_key="readonly-foreign",
        )
        InventorySnapshot.objects.create(
            tenant=self.other_tenant, warehouse=other_warehouse, source_run=foreign_run, site_code="PH",
            source_sku="FOREIGN", snapshot_at_utc=self.now, available_qty=99, payload_hash="f" * 64,
        )

        response = self.client.get(
            self.base_url + f"inventory_workbench/?cursor={old.pk}", **self.headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["data"]["items"]
        self.assertEqual([row["id"] for row in rows], [latest.pk])
        self.assertEqual(rows[0]["available_qty"], 2)
        self.assertEqual(rows[0]["provided_quantity_fields"], ["available_qty"])
        self.assertNotIn(other_platform.pk, [row.get("platform_id") for row in rows])
        historical = self.get_items("inventory_snapshots")
        self.assertEqual({row["id"] for row in historical}, {old.pk, latest.pk})

    def test_advertising_projection_nulls_malformed_metrics_and_precision(self):
        _, run = self.create_run("advertising_report", "advertising")
        ShopeeAdvertisingRecord.objects.create(
            tenant=self.tenant, store=self.store, source_run=run, kind="shop_daily",
            record_key="readonly-shop-report", report_date=date(2026, 10, 1), currency="PHP",
            report_timezone="Asia/Manila", data={
                "expense": "0.000001", "clicks": 4, "ctr": "0.1250", "direct_gmv": "12.340000",
                "broad_gmv": "bad", "direct_order": True, "impression": None, "direct_roas": "Infinity",
            },
        )
        ShopeeAdvertisingRecord.objects.create(
            tenant=self.tenant, store=self.store, source_run=run, kind="campaign_daily",
            record_key="readonly-campaign-report", report_date=date(2026, 10, 1),
            campaign_id="campaign-1", currency="PHP", report_timezone="Asia/Manila",
            data={"expense": "2.500000", "broad_roas": "1.2500"},
        )
        overview = self.get_items("advertising_overview")
        self.assertEqual(len(overview), 1)
        shop = overview[0]
        self.assertEqual(shop["expense"], "0.000001")
        self.assertEqual(shop["clicks"], "4")
        self.assertEqual(shop["ctr"], "0.1250")
        self.assertEqual(shop["direct_gmv"], "12.340000")
        self.assertIsNone(shop["broad_gmv"])
        self.assertIsNone(shop["direct_order"])
        self.assertIsNone(shop["impression"])
        self.assertIsNone(shop["direct_roas"])
        self.assertEqual(len(self.get_items("advertising_performance")), 1)
        self.assertEqual(self.get_items("advertising_performance")[0]["broad_roas"], "1.2500")

    def test_every_published_sales_inventory_and_advertising_route_compiles_and_is_get_only(self):
        codes = set(CONTRACTS)
        self.assertTrue(codes)
        self.assertTrue(codes.issubset(READY.keys()))
        self.assertTrue(codes.issubset(self.resources.keys()))
        for code in sorted(codes):
            response = self.client.get(self.base_url + f"{code}/", **self.headers)
            self.assertEqual(response.status_code, 200, f"{code}: {response.status_code} {response.content!r}")
            self.assertIn("items", response.json()["data"], code)
            self.assertEqual(
                set(response.json()["data"]["items"][0]) if response.json()["data"]["items"] else set(),
                set(READY[code][1]) if response.json()["data"]["items"] else set(),
            )
        for method in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            response = method(self.base_url + "sales_orders/", {}, format="json", **self.headers)
            self.assertEqual(response.status_code, 405)

    def test_authentication_tenant_and_resource_grant_boundaries(self):
        self.assertEqual(self.client.get(self.base_url + "sales_orders/").status_code, 401)
        self.client_obj.resources = {}
        self.client_obj.save(update_fields=["resources"])
        response = self.client.get(self.base_url + "sales_orders/", **self.headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(self.base_url + "not_a_real_contract/", **self.headers).status_code, 404)

    def test_allowlisted_filters_and_malformed_filter_parameters(self):
        config, run = self.create_run("sales_order", "filters")
        matching = self.create_order(run, config, "filter-match", amount="3.1415")
        self.create_order(run, config, "filter-other-currency", currency="USD", amount="7.0000")
        self.create_order(run, config, "filter-other-day", day=date(2026, 9, 30), amount="9.0000")

        response = self.client.get(
            self.base_url + f"sales_orders/?store_id={self.store.pk}&currency=PHP&date_from=2026-10-01&date_to=2026-10-01",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item["id"] for item in response.json()["data"]["items"]], [matching.pk])
        by_id = self.client.get(self.base_url + f"sales_orders/?id={matching.pk}", **self.headers)
        self.assertEqual(by_id.status_code, 200, by_id.content)
        self.assertEqual([item["id"] for item in by_id.json()["data"]["items"]], [matching.pk])

        for query in (
            "?unknown_dimension=1",
            "?date_from=2026-13-01",
            "?date_from=2026-10-02&date_to=2026-10-01",
            "?id=0",
            "?store_id=not-an-integer",
        ):
            invalid = self.client.get(self.base_url + f"sales_orders/{query}", **self.headers)
            self.assertEqual(invalid.status_code, 400, f"{query}: {invalid.content!r}")
