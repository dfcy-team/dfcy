import importlib
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.permissions.models import Permission, Role, UserRole
from apps.tenants.models import Tenant
from apps.demo_sync.models import SyncEnvironment, SnapshotBatch
from apps.demo_sync.service import ReadonlyClient, SyncFailure, verified_bundle_files


class DemoSyncAPITests(TestCase):
    base = "/api/internal/demo-data-sync/"

    def setUp(self):
        self.tenant = Tenant.objects.create(code="SYNC-A", name="Synthetic A")
        self.other_tenant = Tenant.objects.create(code="SYNC-B", name="Synthetic B")
        self.user = get_user_model().objects.create_user(username="sync-owner", tenant=self.tenant, user_type="internal")
        self.peer = get_user_model().objects.create_user(username="sync-peer", tenant=self.tenant, user_type="internal")
        self.foreign = get_user_model().objects.create_user(username="sync-foreign", tenant=self.other_tenant, user_type="internal")
        self.role = Role.objects.create(tenant=self.tenant, code="demo-dev", name="Demo developer")
        for action in ("view", "run", "download"):
            perm, _ = Permission.objects.get_or_create(code=f"system.demo_sync.{action}", defaults={"name": action, "module": "system", "action": action})
            self.role.permissions.add(perm)
        UserRole.objects.create(tenant=self.tenant, user=self.user, role=self.role)
        self.env = SyncEnvironment.objects.create(tenant=self.tenant, owner=self.user, name="A", resources=["sales_orders"], store_ids=[1], warehouse_ids=[])
        self.peer_env = SyncEnvironment.objects.create(tenant=self.tenant, owner=self.peer, name="B", resources=["products"])
        self.foreign_env = SyncEnvironment.objects.create(tenant=self.other_tenant, owner=self.foreign, name="C", resources=["products"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_permission_migration_registers_menu_without_changing_role_grants(self):
        register = importlib.import_module(
            "apps.demo_sync.migrations.0002_register_permissions"
        ).register

        role_permissions_before = set(self.role.permissions.values_list("code", flat=True))
        user_roles_before = set(UserRole.objects.values_list("tenant_id", "user_id", "role_id"))
        Permission.objects.filter(code="menu.system.demo_data_sync.view").delete()
        catalog_codes_before = set(Permission.objects.values_list("code", flat=True))
        role_grants_before = set(Role.permissions.through.objects.values_list("role_id", "permission_id"))

        register(django_apps, None)

        menu = Permission.objects.get(code="menu.system.demo_data_sync.view")
        self.assertEqual(
            (menu.name, menu.module, menu.action, menu.description, menu.permission_type),
            ("开发环境数据同步", "system", "demo_data_sync.view", "显示开发环境数据同步入口", "menu"),
        )
        self.assertEqual(
            menu.metadata,
            {
                "path": "/system/demo-data-sync",
                "route": "/system/demo-data-sync",
                "resource": "system_demo_data_sync",
                "parent": "系统管理",
                "action_codes": ["system.demo_sync.view"],
                "source": "frontend/src/router/menu.js",
                "status": "active",
            },
        )
        catalog_codes_after = set(Permission.objects.values_list("code", flat=True))
        self.assertEqual(
            catalog_codes_after - catalog_codes_before,
            {"menu.system.demo_data_sync.view"},
        )
        self.assertEqual(
            set(
                Permission.objects.filter(code__startswith="system.demo_sync.").values_list(
                    "code", flat=True
                )
            ),
            {
                "system.demo_sync.view",
                "system.demo_sync.manage",
                "system.demo_sync.run",
                "system.demo_sync.download",
            },
        )
        self.assertEqual(
            set(
                Permission.objects.filter(code__startswith="menu.system.demo_data_sync.").values_list(
                    "code", flat=True
                )
            ),
            {"menu.system.demo_data_sync.view"},
        )
        self.assertEqual(set(self.role.permissions.values_list("code", flat=True)), role_permissions_before)
        self.assertEqual(set(UserRole.objects.values_list("tenant_id", "user_id", "role_id")), user_roles_before)
        self.assertEqual(
            set(Role.permissions.through.objects.values_list("role_id", "permission_id")),
            role_grants_before,
        )

    def manage(self):
        perm, _ = Permission.objects.get_or_create(code="system.demo_sync.manage", defaults={"name": "Manage", "module": "system", "action": "manage"})
        self.role.permissions.add(perm)

    def queue(self, **overrides):
        return self.client.post(self.base + "batches/", {"environment_id": self.env.pk, "date_from": "2026-10-01", "date_to": "2026-10-02", **overrides}, format="json")

    def test_unauthenticated_denied(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.base + "options/").status_code, (401, 403))

    def test_peer_and_foreign_environments_hidden(self):
        rows = self.client.get(self.base + "environments/").json()["data"]["results"]
        self.assertEqual([x["id"] for x in rows], [self.env.pk])

    @override_settings(DEMO_DATA_SYNC_ENABLED=True)
    def test_ownership_and_tenant_checked_when_queueing(self):
        self.assertEqual(self.queue(environment_id=self.peer_env.pk).status_code, 404)
        self.assertEqual(self.queue(environment_id=self.foreign_env.pk).status_code, 404)
        self.assertEqual(SnapshotBatch.objects.count(), 0)

    def test_default_off_does_not_create_task(self):
        response = self.queue()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["success"])
        self.assertEqual(SnapshotBatch.objects.count(), 0)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True)
    def test_queue_returns_202_and_duplicate_rejected(self):
        self.assertEqual(self.queue().status_code, 202)
        batch = SnapshotBatch.objects.get()
        self.assertEqual(batch.status, "queued")
        self.assertEqual(list(batch.audit.values_list("event", flat=True)), ["batch.queued"])
        self.assertEqual(self.queue().status_code, 400)
        self.assertEqual(SnapshotBatch.objects.count(), 1)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True)
    def test_invalid_window_and_inactive_environment_rejected(self):
        self.assertEqual(self.queue(date_to="2026-11-02").status_code, 400)
        self.assertEqual(self.queue(date_to="2026-09-30").status_code, 400)
        self.env.active = False
        self.env.save()
        self.assertEqual(self.queue().status_code, 400)

    def test_manage_does_not_expose_other_tenant(self):
        self.manage()
        rows = self.client.get(self.base + "environments/").json()["data"]["results"]
        self.assertEqual(set(x["id"] for x in rows), {self.env.pk, self.peer_env.pk})

    def test_environment_requires_explicit_scope_and_tenant_owner(self):
        self.manage()
        payload = {"name": "new", "owner_id": self.user.pk, "resources": ["sales_orders"], "store_ids": [], "warehouse_ids": []}
        self.assertEqual(self.client.post(self.base + "environments/", payload, format="json").status_code, 400)
        payload.update(store_ids=[1], owner_id=self.foreign.pk)
        self.assertEqual(self.client.post(self.base + "environments/", payload, format="json").status_code, 400)
        payload["owner_id"] = self.user.pk
        self.assertEqual(self.client.post(self.base + "environments/", payload, format="json").status_code, 201)

    def test_management_permission_required(self):
        self.assertEqual(self.client.post(self.base + "environments/", {}, format="json").status_code, 403)

    def test_revoke_does_not_allow_scope_mutation(self):
        self.manage()
        path = self.base + f"environments/{self.env.pk}/"
        self.assertEqual(self.client.patch(path, {"active": False, "store_ids": [3]}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(path, {"active": False}, format="json").status_code, 200)
        self.env.refresh_from_db()
        self.assertFalse(self.env.active)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True)
    def test_download_rejects_non_ready_revoked_and_foreign(self):
        batch = SnapshotBatch.objects.create(tenant=self.tenant, environment=self.env, requested_by=self.user, date_from=date(2026, 10, 1), date_to=date(2026, 10, 2))
        url = self.base + f"batches/{batch.pk}/download/"
        self.assertEqual(self.client.get(url).status_code, 400)
        batch.environment = self.peer_env
        batch.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True)
    def test_revocation_releases_queued_environment(self):
        self.manage()
        self.assertEqual(self.queue().status_code, 202)
        path = self.base + f"environments/{self.env.pk}/"
        self.assertEqual(self.client.patch(path, {"active": False}, format="json").status_code, 200)
        batch = SnapshotBatch.objects.get()
        self.assertEqual((batch.status, batch.error_code), ("failed", "ENVIRONMENT_REVOKED"))
        self.client.patch(path, {"active": True}, format="json")
        self.assertEqual(self.queue().status_code, 202)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True, DEMO_DATA_SYNC_WORKER_ENABLED=True)
    def test_worker_builds_validated_bundle_and_download_audit(self):
        from apps.demo_sync.tests.test_importer import FixtureClient
        from apps.demo_sync.pipeline import RESOURCES
        from apps.demo_sync.service import run_batch
        self.env.resources, self.env.store_ids, self.env.warehouse_ids = list(RESOURCES), [10], [20]
        self.env.save()
        self.assertEqual(self.queue().status_code, 202)
        batch = SnapshotBatch.objects.get()
        with tempfile.TemporaryDirectory() as folder, override_settings(DEMO_DATA_SYNC_ARTIFACT_ROOT=folder):
            batch = run_batch(batch.pk, client=FixtureClient())
            self.assertEqual(batch.status, "ready", batch.error_code)
            self.assertGreater(batch.summary["rows"], 0)
            response = self.client.get(self.base + f"batches/{batch.pk}/download/")
            self.assertEqual(response.status_code, 200)
            response.close()
            self.assertTrue(batch.audit.filter(event="batch.downloaded").exists())

    @override_settings(DEMO_DATA_SYNC_ENABLED=True, DEMO_DATA_SYNC_WORKER_ENABLED=True)
    def test_running_revocation_stops_next_page_and_publication(self):
        from apps.demo_sync.tests.test_importer import FixtureClient
        from apps.demo_sync.pipeline import RESOURCES
        from apps.demo_sync.service import run_batch
        self.env.resources, self.env.store_ids, self.env.warehouse_ids = list(RESOURCES), [10], [20]
        self.env.save()
        self.queue()
        batch = SnapshotBatch.objects.get()
        env_id = self.env.pk

        class RevokingClient(FixtureClient):
            calls = 0

            def fetch(self, resource, params):
                self.calls += 1
                result = super().fetch(resource, params)
                SyncEnvironment.objects.filter(pk=env_id).update(active=False)
                return result

        fake = RevokingClient()
        with tempfile.TemporaryDirectory() as folder, override_settings(DEMO_DATA_SYNC_ARTIFACT_ROOT=folder):
            result = run_batch(batch.pk, client=fake)
        self.assertEqual(result.error_code, "ENVIRONMENT_REVOKED")
        self.assertEqual(result.status, "failed")
        self.assertEqual(fake.calls, 1)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True)
    def test_stale_worker_lease_can_be_recovered(self):
        self.queue()
        batch = SnapshotBatch.objects.get()
        batch.status = "running"
        batch.started_at = batch.heartbeat_at = timezone.now() - timedelta(minutes=11)
        batch.save()
        response = self.client.post(self.base + f"batches/{batch.pk}/retry/", {}, format="json")
        self.assertEqual(response.status_code, 202)
        batch.refresh_from_db()
        self.assertEqual(batch.error_code, "WORKER_LEASE_EXPIRED")
        self.assertEqual(SnapshotBatch.objects.count(), 2)


class TransportSafetyTests(TestCase):
    @override_settings(DEMO_DATA_SYNC_ALLOWED_HOSTS=["allowed.example"])
    def test_unapproved_hosts_http_and_userinfo_rejected(self):
        for url in ("http://allowed.example", "https://elsewhere.example", "https://a:b@allowed.example", "https://allowed.example/other", "https://allowed.example?x=1"):
            with self.assertRaises(SyncFailure):
                ReadonlyClient({"url": url})

    def test_manifest_traversal_and_secret_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "manifest.json").write_text(json.dumps({"schema_version": "demo-snapshot.v1", "deidentified": True, "files": [{"resource": "products", "path": "../escape", "count": 0, "sha256": ""}]}), encoding="utf-8")
            with self.assertRaises(SyncFailure):
                verified_bundle_files(folder)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True, DEMO_DATA_SYNC_WORKER_ENABLED=False)
    def test_worker_defaults_off(self):
        from apps.demo_sync.service import run_batch
        with self.assertRaisesMessage(SyncFailure, "WORKER_DISABLED"):
            run_batch("00000000-0000-0000-0000-000000000000")
