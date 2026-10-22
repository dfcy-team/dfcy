"""Create synthetic fixtures for isolated local V278 acceptance runs only."""

import hashlib
import json
import secrets
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


SAFE_DATABASES = {
    "source": "saas_collab_demo_source_acceptance",
    "control": "saas_collab_sync_acceptance",
    "target": "saas_collab_demo_target_acceptance",
}
FIXTURE_CODES = {
    "source": "demo-sync-accept-source",
    "control": "demo-sync-accept-control",
    "target": "demo-sync-accept-target",
}
FIXTURE_PREFIX = "demo-sync-accept-"
FIXTURE_TIME = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _check_local_database(role):
    db = connection.settings_dict
    if not getattr(settings, "DEMO_SYNC_LOCAL_ACCEPTANCE", False):
        raise CommandError("Refusing seed: DEMO_SYNC_LOCAL_ACCEPTANCE must be True.")
    expected_name = SAFE_DATABASES[role]
    if db.get("HOST") != "127.0.0.1" or str(db.get("PORT")) != "13326" or db.get("NAME") != expected_name:
        raise CommandError("Refusing seed: database host, port, or role-specific name is not the isolated acceptance database.")


def _check_config_path(path):
    path = path.expanduser().resolve()
    workspace = Path(settings.BASE_DIR).parent.parents[2]
    expected = workspace / ".codex-tmp" / "demo-sync-local-acceptance-20261022" / "private-config.json"
    if path != expected.resolve() or not path.is_file() or path.is_symlink():
        raise CommandError("Only the isolated acceptance runtime config may be read.")
    return path


def _new_credentials():
    return {
        "login_password": secrets.token_urlsafe(24),
        "client_id": "demo-sync-" + secrets.token_hex(16),
        "client_secret": secrets.token_urlsafe(36),
    }


def _ensure_no_fixture(tenant_code, username, business_models=()):
    from apps.tenants.models import Tenant

    User = get_user_model()
    if Tenant.objects.filter(code=tenant_code).exists() or User.objects.filter(username=username).exists():
        raise CommandError("Acceptance fixture already exists; refusing to duplicate or overwrite it.")
    for model, field in business_models:
        if model.objects.filter(**{f"{field}__startswith": FIXTURE_PREFIX}).exists():
            raise CommandError("A same-name acceptance business fixture already exists; refusing to continue.")


def _tenant_and_user(code, name, username, password):
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.create(code=code, name=name)
    user = get_user_model().objects.create_user(
        username=username, tenant=tenant, user_type="internal", is_active=True, password=password,
    )
    return tenant, user


def _seed_source(credentials):
    from apps.commerce.models import InventorySnapshot, SalesOrder, SalesOrderItem
    from apps.integrations.models import InternalAPIClient, PlatformIntegrationConfig, SyncJob, SyncRun
    from apps.integrations.readonly_domains import CONTRACTS
    from apps.integrations.serializers import INTERNAL_API_RESOURCE_FIELDS
    from apps.masterdata.models import CountrySiteMaster, PlatformMaster, StoreMaster, WarehouseMaster
    from apps.products.models import ProductSKU, ProductSPU
    from apps.tenants.models import Tenant

    tenant_code = FIXTURE_CODES["source"]
    username = "demo-sync-source-acceptance"
    _ensure_no_fixture(tenant_code, username, (
        (PlatformMaster, "code"), (CountrySiteMaster, "code"), (StoreMaster, "code"),
        (WarehouseMaster, "code"), (ProductSPU, "spu_code"), (ProductSKU, "sku_code"),
    ))
    tenant, user = _tenant_and_user(tenant_code, "Demo sync source acceptance", username, credentials["login_password"])

    platform = PlatformMaster.objects.create(
        tenant=tenant, code="demo-sync-accept-shopee", name="Shopee", platform_type="shopee",
    )
    CountrySiteMaster.objects.create(
        tenant=tenant, code="demo-sync-accept-ph", name="Philippines", country_code="PH",
        platform="shopee", currency="PHP", timezone="Asia/Manila",
    )
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="demo-sync-accept-store", name="Acceptance Shopee store",
        country_code="PH", currency="PHP", settlement_currency="PHP", timezone="Asia/Manila",
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code="demo-sync-accept-warehouse", name="Acceptance warehouse",
        country_code="PH", warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="DSA-SPU-20261020", product_name="Acceptance travel mug",
        lifecycle_status=ProductSPU.LifecycleStatus.ACTIVE,
    )
    sku = ProductSKU.objects.create(
        id=101,
        tenant=tenant, spu=spu, sku_code="DSA-SKU-20261020", product_name="Acceptance travel mug, blue",
        color_code="BLUE", is_active=True,
    )

    shopee_config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="shopee", account_alias="demo-sync-accept-shopee",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.DISABLED, network_enabled=False,
        sync_read_enabled=False, sync_write_enabled=False, platform_config={},
        created_by=user,
    )
    wms_config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="jifeng_wms", account_alias="demo-sync-accept-jifeng-wms",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.DISABLED, network_enabled=False,
        sync_read_enabled=False, sync_write_enabled=False, platform_config={},
        created_by=user,
    )

    def run(config, resource, slug, fetched):
        job = SyncJob.objects.create(
            tenant=tenant, integration_config=config, resource_type=resource,
            status=SyncJob.Status.DISABLED, is_enabled=False,
        )
        return SyncRun.objects.create(
            tenant=tenant, sync_job=job, run_id=f"demo-sync-accept-{slug}",
            idempotency_key=f"demo-sync-accept-{slug}", status=SyncRun.Status.SUCCESS,
            started_at=FIXTURE_TIME, finished_at=FIXTURE_TIME,
            fetched_count=fetched, created_count=fetched, failed_count=0,
            masked_log={"fixture": "synthetic-local-acceptance", "external_api_called": False},
        )

    order_run = run(shopee_config, SyncJob.ResourceType.SALES_ORDER, "sales-orders", 2)
    inventory_run = run(wms_config, SyncJob.ResourceType.INVENTORY_SNAPSHOT, "inventory", 1)
    order = SalesOrder.objects.create(
        tenant=tenant, platform=platform, store=store, authorization=shopee_config,
        source_run=order_run, external_order_id="DSA-ORDER-COMPLETED-20261020",
        region="PH", raw_status="COMPLETED", normalized_status="completed",
        status_mapping_version="1.0", created_at_utc=FIXTURE_TIME, updated_at_utc=FIXTURE_TIME,
        completed_at_utc=FIXTURE_TIME, business_date=date(2026, 10, 20), currency="PHP",
        subtotal_amount="20.1234", order_total_amount="20.1234", payload_hash="a" * 64,
    )
    SalesOrderItem.objects.create(
        sales_order=order, internal_spu=spu, internal_sku=sku,
        external_line_id="DSA-LINE-1", platform_product_id="DSA-PRODUCT-1",
        platform_variant_id="DSA-VARIANT-1", seller_sku=sku.sku_code,
        item_name_snapshot=sku.product_name, quantity=2, original_unit_price="10.0617",
        sale_unit_price="9.0617", line_total_amount="18.1234", currency="PHP",
    )
    SalesOrder.objects.create(
        tenant=tenant, platform=platform, store=store, authorization=shopee_config,
        source_run=order_run, external_order_id="DSA-ORDER-CANCELLED-20261020",
        region="PH", raw_status="CANCELLED", normalized_status="cancelled",
        status_mapping_version="1.0", created_at_utc=FIXTURE_TIME, updated_at_utc=FIXTURE_TIME,
        cancelled_at_utc=FIXTURE_TIME, business_date=date(2026, 10, 20), currency="PHP",
        subtotal_amount="3.0000", order_total_amount="3.0000", payload_hash="b" * 64,
    )
    InventorySnapshot.objects.create(
        tenant=tenant, site_code="PH", warehouse=warehouse, internal_sku=sku,
        source_run=inventory_run, source_sku=sku.sku_code, seller_sku=sku.sku_code,
        on_hand_qty=9, available_qty=8, reserved_qty=1,
        provided_quantity_fields=["on_hand_qty", "available_qty", "reserved_qty"],
        snapshot_at_utc=FIXTURE_TIME, payload_hash="c" * 64,
    )
    secret = credentials["client_secret"]
    from apps.demo_sync.contracts import RESOURCES
    resources = {code: sorted(INTERNAL_API_RESOURCE_FIELDS[code]) for code in RESOURCES}
    client = InternalAPIClient.objects.create(
        tenant=tenant, created_by=user, updated_by=user, approved_by=user,
        name="Demo sync local acceptance readonly client", caller_type=InternalAPIClient.CallerType.INTERNAL_SYSTEM,
        client_id=credentials["client_id"], secret_hash=make_password(secret),
        secret_prefix=secret[:12], secret_fingerprint=hashlib.sha256(secret.encode()).hexdigest(),
        resources=resources, allowed_cidrs=["127.0.0.1/32"], rate_limit_per_minute=10000,
        page_size_limit=1000, allow_sso_login=False, sso_redirect_uris=[], status=InternalAPIClient.Status.ACTIVE,
        approval_status=InternalAPIClient.ApprovalStatus.APPROVED,
        approved_at=FIXTURE_TIME, reviewed_at=FIXTURE_TIME,
    )
    return {
        "tenant_id": tenant.pk, "user_id": user.pk,
        "store_id": store.pk, "warehouse_id": warehouse.pk,
        "spu_id": spu.pk, "sku_id": sku.pk,
        "resource_counts": {
            "platforms": 1, "country_sites": 1, "stores": 1, "warehouses": 1,
            "spus": 1, "skus": 1, "sales_orders": 2, "sales_order_items": 1,
            "inventory_snapshots": 1, "resources_authorized": len(resources),
        },
    }


def _seed_control(credentials):
    from apps.permissions.models import DataScope, Permission, Role, UserRole

    tenant_code = FIXTURE_CODES["control"]
    username = "demo-sync-acceptance"
    _ensure_no_fixture(tenant_code, username)
    tenant, user = _tenant_and_user(tenant_code, "Demo sync control acceptance", username, credentials["login_password"])
    role = Role.objects.create(
        tenant=tenant, name="Demo sync acceptance", code="demo-sync-acceptance",
        role_type=Role.RoleType.CUSTOM, status=Role.Status.ACTIVE,
    )
    action_codes = [f"system.demo_sync.{action}" for action in ("view", "run", "manage", "download")]
    labels = ("查看开发环境数据同步", "执行开发数据快照", "管理开发同步环境", "下载开发数据快照")
    for code, label in zip(action_codes, labels):
        Permission.objects.get_or_create(code=code, defaults={
            "name": label, "module": "system", "action": "demo_sync." + code.rsplit(".", 1)[-1],
        })
    menu, _ = Permission.objects.update_or_create(
        code="menu.system.demo_data_sync.view",
        defaults={"name": "开发环境数据同步", "module": "system", "action": "demo_data_sync.view",
                  "permission_type": Permission.PermissionType.MENU},
    )
    role.permissions.add(*Permission.objects.filter(code__in=action_codes), menu)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    UserRole.objects.create(
        tenant=tenant, user=user, role=role, context_key="tenant", source="acceptance_seed",
        status=Role.Status.ACTIVE, assigned_by=user,
    )
    return {"tenant_id": tenant.pk, "user_id": user.pk, "role_id": role.pk}


def _seed_target(credentials):
    tenant_code = FIXTURE_CODES["target"]
    username = "demo-sync-target-acceptance"
    _ensure_no_fixture(tenant_code, username)
    tenant, user = _tenant_and_user(tenant_code, "Demo sync target acceptance", username, credentials["login_password"])
    return {"tenant_id": tenant.pk, "user_id": user.pk}


class Command(BaseCommand):
    help = "Seed synthetic acceptance fixtures in a guarded local MySQL database."

    def add_arguments(self, parser):
        parser.add_argument("--role", required=True, choices=tuple(SAFE_DATABASES))
        parser.add_argument("--config", required=True, type=Path)

    def handle(self, *args, **options):
        role = options["role"]
        _check_local_database(role)
        config_path = _check_config_path(options["config"])
        credentials = json.loads(config_path.read_text(encoding="utf-8"))
        if any(not isinstance(credentials.get(key), str) or len(credentials[key]) < 20
               for key in ("login_password", "client_id", "client_secret")):
            raise CommandError("Synthetic runtime credentials are missing.")
        with transaction.atomic():
            if role == "source":
                fixture_ids = _seed_source(credentials)
            elif role == "control":
                fixture_ids = _seed_control(credentials)
            else:
                fixture_ids = _seed_target(credentials)
        self.stdout.write(json.dumps({"status": "seeded", "role": role, **fixture_ids}, sort_keys=True))
