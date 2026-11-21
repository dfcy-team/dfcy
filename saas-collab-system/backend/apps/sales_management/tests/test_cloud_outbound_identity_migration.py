"""Synthetic in-memory upgrade checks; no provider, cloud DB or business payload."""
import hashlib
import importlib
import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.db import connection, migrations, models
from django.db.migrations.state import ModelState, ProjectState
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

fill = importlib.import_module("apps.sales_management.migrations.0014_fill_outbound_identity_preserving_rows")
contract = importlib.import_module("apps.sales_management.migrations.0015_enforce_outbound_identity")


def fk(target):
    return models.ForeignKey(target, on_delete=models.PROTECT)


def synthetic_state():
    state = ProjectState()
    definitions = [
        ("tenants", "Tenant", []),
        ("masterdata", "StoreMaster", [("tenant", fk("tenants.Tenant")), ("country_code", models.CharField(max_length=8))]),
        ("masterdata", "WarehouseMaster", [("tenant", fk("tenants.Tenant")), ("country_code", models.CharField(max_length=8))]),
        ("commerce", "SalesOrder", [("tenant", fk("tenants.Tenant")), ("store", fk("masterdata.StoreMaster")), ("region", models.CharField(max_length=40))]),
        ("sales_management", "OrderWarehouseLookup", [("order", fk("commerce.SalesOrder")), ("warehouse", fk("masterdata.WarehouseMaster")), ("snapshot", models.JSONField(default=dict))]),
        ("sales_management", "WarehouseOutboundLine", [
            ("lookup", fk("sales_management.OrderWarehouseLookup")), ("tenant", fk("tenants.Tenant")),
            ("warehouse", fk("masterdata.WarehouseMaster")), ("document", models.CharField(max_length=191)),
            ("warehouse_sku", models.CharField(max_length=191, blank=True)), ("source_sku", models.CharField(max_length=191, blank=True)),
            ("quantity", models.PositiveBigIntegerField()), ("shipped_at", models.DateTimeField()),
            ("site_code", models.CharField(max_length=8, null=True)), ("document_key", models.CharField(max_length=64, null=True)),
            ("identity_key", models.CharField(max_length=64, null=True)),
        ]),
    ]
    for app, name, fields in definitions:
        state.add_model(ModelState(app, name, [("id", models.AutoField(primary_key=True)), *fields], options={"db_table": "v518_test_" + app + "_" + name.lower()}))
    return state


class OutboundIdentityMigrationTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "sqlite")
        self.assertIn(connection.settings_dict["NAME"], (":memory:", "file:memorydb_default?mode=memory&cache=shared"))
        self.state = synthetic_state()
        self.apps = self.state.apps
        names = [("tenants", "Tenant"), ("masterdata", "StoreMaster"), ("masterdata", "WarehouseMaster"), ("commerce", "SalesOrder"), ("sales_management", "OrderWarehouseLookup"), ("sales_management", "WarehouseOutboundLine")]
        self.models = [self.apps.get_model(*name) for name in names]
        with connection.schema_editor() as editor:
            for model in self.models:
                editor.create_model(model)
        Tenant, Store, Warehouse, Order, Lookup, self.Line = self.models
        self.tenant = Tenant.objects.create()
        self.store = Store.objects.create(tenant=self.tenant, country_code="PH")
        self.warehouse = Warehouse.objects.create(tenant=self.tenant, country_code="PH")
        self.order = Order.objects.create(tenant=self.tenant, store=self.store, region="PH")
        self.lookup = Lookup.objects.create(order=self.order, warehouse=self.warehouse, snapshot={"packages": []})
        self.editor = type("Editor", (), {"connection": connection})()

    def tearDown(self):
        with connection.schema_editor() as editor:
            for model in reversed(self.models):
                editor.delete_model(model)

    def line(self, **changes):
        values = dict(lookup=self.lookup, tenant=self.tenant, warehouse=self.warehouse, document="出库-α", warehouse_sku="仓库-SKU", source_sku="来源-SKU", quantity=3, shipped_at=datetime(2026, 11, 20, 1, tzinfo=timezone.utc))
        values.update(changes)
        return self.Line.objects.create(**values)

    def run_fill(self):
        fill.fill_identity(self.apps, self.editor)

    def protected(self):
        return list(self.Line.objects.order_by("pk").values_list(*fill.LEGACY_FIELDS))

    def test_uses_recorded_order_country_preserves_ids_values_and_unicode_keys(self):
        row = self.line()
        before = self.protected()
        with CaptureQueriesContext(connection) as queries:
            self.run_fill()
        self.assertEqual(self.protected(), before)
        row.refresh_from_db()
        self.assertEqual(row.site_code, "PH")
        self.assertEqual(row.document_key, hashlib.sha256(row.document.encode()).hexdigest())
        expected = json.dumps([row.document, row.warehouse_sku, row.source_sku], ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(row.identity_key, hashlib.sha256(expected.encode()).hexdigest())
        writes = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
        self.assertTrue(writes)
        self.assertTrue(all(q.startswith("UPDATE") for q in writes))
        self.assertTrue(all(connection.ops.quote_name("quantity") not in q and connection.ops.quote_name("document") not in q for q in writes))
        contract.require_complete_keys(self.apps, self.editor)

    def test_exact_snapshot_country_and_recorded_region_must_agree(self):
        self.lookup.snapshot = {"site_code": "MY"}
        self.lookup.save()
        self.line()
        with self.assertRaisesRegex(RuntimeError, "V518_OUTBOUND_COUNTRY_CONFLICT"):
            self.run_fill()
        self.assertIsNone(self.Line.objects.get().identity_key)

    def test_current_configuration_is_not_a_country_source(self):
        self.order.region = ""
        self.order.save()
        self.line()
        with self.assertRaisesRegex(RuntimeError, "MISSING_PERSISTED_COUNTRY"):
            self.run_fill()

    def test_country_and_tenant_relation_conflicts_fail_closed(self):
        row = self.line()
        self.warehouse.country_code = "TH"
        self.warehouse.save()
        with self.assertRaisesRegex(RuntimeError, "COUNTRY_RELATION_CONFLICT"):
            self.run_fill()
        self.warehouse.country_code = "PH"
        self.warehouse.save()
        other = self.models[0].objects.create()
        self.Line.objects.filter(pk=row.pk).update(tenant_id=other.pk)
        with self.assertRaisesRegex(RuntimeError, "RELATION_CONFLICT"):
            self.run_fill()

    def test_invalid_later_row_rolls_back_all_prior_chunks(self):
        self.line(document="A")
        self.line(document="B ")
        before = self.protected()
        with patch.object(fill, "BATCH_SIZE", 1):
            with self.assertRaisesRegex(RuntimeError, "NONCANONICAL_IDENTITY"):
                self.run_fill()
        self.assertEqual(self.protected(), before)
        self.assertEqual(self.Line.objects.filter(identity_key__isnull=True).count(), 2)

    def test_collision_rolls_back_new_values_without_rebuilding(self):
        self.line(document="A")
        self.line(document="B")
        before = self.protected()
        with patch.object(fill, "derive_identity", return_value=("PH", "d" * 64, "i" * 64)):
            with self.assertRaisesRegex(RuntimeError, "IDENTITY_COLLISION"):
                self.run_fill()
        self.assertEqual(self.protected(), before)
        self.assertEqual(self.Line.objects.filter(identity_key__isnull=True).count(), 2)

    def test_existing_derived_conflicts_are_not_overwritten(self):
        row = self.line(site_code="TH")
        with self.assertRaisesRegex(RuntimeError, "EXISTING_DERIVED_VALUE_CONFLICT"):
            self.run_fill()
        row.refresh_from_db()
        self.assertEqual(row.site_code, "TH")

    def test_confirmed_repeat_is_idempotent_in_synthetic_db(self):
        self.line()
        self.run_fill()
        before = list(self.Line.objects.values())
        self.run_fill()
        self.assertEqual(list(self.Line.objects.values()), before)

    def test_contract_rejects_old_writer_nulls(self):
        self.line()
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE_BEFORE_CONTRACT"):
            contract.require_complete_keys(self.apps, self.editor)

    def test_resource_gate_and_zero_quantity_fail_without_changes(self):
        self.line(quantity=0)
        with patch.object(fill, "MAX_LEGACY_ROWS", 0):
            with self.assertRaisesRegex(RuntimeError, "RESOURCE_BUDGET_REQUIRES_REVIEW"):
                self.run_fill()
        with self.assertRaisesRegex(RuntimeError, "INVALID_QUANTITY"):
            self.run_fill()

    def test_keyset_pages_are_bounded_and_cover_each_id_once(self):
        for i in range(7):
            self.line(document="D" + str(i))
        upper_pk = self.Line.objects.order_by("-pk").values_list("pk", flat=True).first()
        with patch.object(fill, "BATCH_SIZE", 2):
            pages = list(fill.keyset_batches(self.Line.objects.values_list("pk"), upper_pk))
        self.assertEqual([len(p) for p in pages], [2, 2, 2, 1])
        self.assertEqual([r[0] for p in pages for r in p], list(self.Line.objects.order_by("pk").values_list("pk", flat=True)))

    def test_contract_keeps_a_lookup_leading_unique_index_at_every_ddl(self):
        active = {"uniq_wh_outbound_lookup_line": ("lookup", "document", "warehouse_sku", "source_sku")}
        for operation in contract.Migration.operations:
            if isinstance(operation, migrations.AddConstraint):
                active[operation.constraint.name] = operation.constraint.fields
            elif isinstance(operation, migrations.RemoveConstraint):
                active.pop(operation.name)
            self.assertTrue(any(fields[0] == "lookup" for fields in active.values()))
        self.assertEqual(active, {"uniq_wh_outbound_lookup_line": ("lookup", "identity_key")})
