"""Real SQLite schema upgrades on synthetic probe tables, never provider traffic."""
from importlib import import_module
from unittest.mock import patch

from django.db import connection, models
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import ModelState, ProjectState
from django.test import SimpleTestCase, TransactionTestCase


APP = "integrations"
OLD = (APP, "0046_syncjob_ads_mapping")
REPLACEMENT = (APP, "0046_syncjob_ads_mapping_compatible")
LEAF = (APP, "0054_daily_ads_shared_raw")


def migration(name):
    return import_module(f"apps.integrations.migrations.{name}").Migration(name, APP)


class ReplacementGraphTests(SimpleTestCase):
    def test_fresh_graph_has_one_leaf_and_uses_replacement(self):
        loader = MigrationLoader(None)
        self.assertEqual(loader.graph.leaf_nodes(APP), [LEAF])
        self.assertNotIn(OLD, loader.graph.nodes)
        self.assertIn(REPLACEMENT, loader.graph.forwards_plan(LEAF))

    def test_legacy_receipt_marks_replacement_applied(self):
        baseline = MigrationLoader(None)
        applied = {key: object() for key in baseline.graph.forwards_plan(REPLACEMENT) if key != REPLACEMENT}
        applied[OLD] = object()
        with patch.object(MigrationRecorder, "applied_migrations", return_value=applied):
            executor = MigrationExecutor(connection)
            loader = executor.loader
        self.assertIn(REPLACEMENT, loader.applied_migrations)
        pending = [(item.app_label, item.name) for item, backwards in executor.migration_plan([LEAF])]
        self.assertNotIn(REPLACEMENT, pending)
        self.assertIn(LEAF, pending)


class UpgradeSchemaTests(TransactionTestCase):
    def setUp(self):
        self.state = ProjectState()
        self.state.add_model(ModelState(APP, "TikTokAdsAdvertiserMapping", [
            ("id", models.AutoField(primary_key=True)),
        ], options={"db_table": "tk_merge_probe_mapping"}))
        self.state.add_model(ModelState(APP, "SyncJob", [
            ("id", models.AutoField(primary_key=True)),
            ("tenant", models.IntegerField()),
            ("resource_type", models.CharField(max_length=40)),
            ("store_authorization", models.IntegerField(null=True)),
            ("warehouse_authorization", models.IntegerField(null=True)),
        ], options={"db_table": "tk_merge_probe_job"}))
        with connection.schema_editor() as editor:
            for name in ("TikTokAdsAdvertiserMapping", "SyncJob"):
                editor.create_model(self.state.apps.get_model(APP, name))

    def tearDown(self):
        with connection.schema_editor() as editor:
            for name in ("SyncJob", "TikTokAdsAdvertiserMapping"):
                editor.delete_model(self.state.apps.get_model(APP, name))
        super().tearDown()

    def apply(self, name):
        with connection.schema_editor() as editor:
            self.state = migration(name).apply(self.state, editor)

    def finish(self):
        self.apply("0047_merge_tiktok_main_integration")
        self.apply("0048_alter_syncjob_resource_type")

    def test_main_shopee_job_survives_upgrade_without_mapping(self):
        job = self.state.apps.get_model(APP, "SyncJob").objects.create(
            tenant=17, resource_type="advertising_report", store_authorization=23)
        self.apply(REPLACEMENT[1])
        self.finish()
        saved = self.state.apps.get_model(APP, "SyncJob").objects.get(pk=job.pk)
        self.assertEqual((saved.tenant, saved.resource_type, saved.store_authorization, saved.ads_mapping_id),
                         (17, "advertising_report", 23, None))

    def test_old_vm_schema_upgrades_without_recreating_mapping_column(self):
        self.apply(OLD[1])
        mapping = self.state.apps.get_model(APP, "TikTokAdsAdvertiserMapping").objects.create()
        job = self.state.apps.get_model(APP, "SyncJob").objects.create(
            tenant=19, resource_type="advertising_report", ads_mapping=mapping)
        self.finish()
        saved = self.state.apps.get_model(APP, "SyncJob").objects.get(pk=job.pk)
        self.assertEqual(saved.ads_mapping_id, mapping.pk)
        columns = connection.introspection.get_table_description(connection.cursor(), "tk_merge_probe_job")
        self.assertEqual(sum(column.name == "ads_mapping_id" for column in columns), 1)
