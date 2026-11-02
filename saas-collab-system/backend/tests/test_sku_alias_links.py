from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.db.models import Max
from django.test.utils import CaptureQueriesContext

from apps.commerce.inventory_sku_mapping import resolve_inventory_sku, resolve_inventory_skus
from apps.products.models import ProductSKU, ProductSPU, ProductSKUAlias
from apps.permissions.models import Role, UserRole
from apps.products.sku_aliases import code_key
from tests.test_sales_management import NOW, create_scope

pytestmark = pytest.mark.django_db


def _alias(sku, code, start, end=None, *, scope_type="warehouse", warehouse=None):
    return ProductSKUAlias.objects.create(
        tenant_id=sku.tenant_id, sku=sku, alias_code=code, code_key=code_key(code),
        scope_type=scope_type, warehouse=warehouse if scope_type == "warehouse" else None,
        effective_from=start, effective_to=end, reason="confirmed legacy identity",
        version_no=(ProductSKUAlias.objects.filter(sku=sku).aggregate(n=Max("version_no"))["n"] or 0) + 1,
    )


def test_inventory_alias_period_exactness_and_multiple_old_codes():
    tenant, _, _, warehouse = create_scope("sku-alias-links")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="ALINK-SPU", product_name="Alias")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="CURRENT")
    start = NOW - timedelta(days=10)
    end = NOW - timedelta(days=2)
    _alias(sku, "OLD-A", start, end, warehouse=warehouse)
    _alias(sku, "OLD-B", start, end, warehouse=warehouse)

    assert resolve_inventory_sku(tenant=tenant, warehouse=warehouse, source_sku="OLD-A", seller_sku="OLD-A", snapshot_at_utc=NOW - timedelta(days=5)) == (sku.id, "exact_catalogue_code")
    assert resolve_inventory_sku(tenant=tenant, warehouse=warehouse, source_sku="OLD-A", seller_sku="OLD-A", snapshot_at_utc=NOW) == (None, "unmatched")
    with CaptureQueriesContext(connection) as queries:
        result = resolve_inventory_skus(tenant=tenant, warehouse=warehouse, sku_pairs=[
            ("OLD-A", "OLD-A", NOW - timedelta(days=5)), ("OLD-B", "OLD-B", NOW - timedelta(days=5)),
        ])
    assert result[("OLD-A", "OLD-A", NOW - timedelta(days=5))][0] == sku.id
    assert result[("OLD-B", "OLD-B", NOW - timedelta(days=5))][0] == sku.id
    alias_selects = [q for q in queries if "productskualias" in q["sql"].lower()]
    assert len(alias_selects) == 1


def test_inventory_dated_alias_conflict_and_original_source_are_preserved():
    tenant, _, _, warehouse = create_scope("sku-alias-conflict")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="CLASH-SPU", product_name="Clash")
    intended = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW-A")
    competing = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="OLD-CODE")
    _alias(intended, "OLD-CODE", NOW - timedelta(days=1), warehouse=warehouse)
    assert resolve_inventory_sku(tenant=tenant, warehouse=warehouse, source_sku="OLD-CODE", seller_sku="OLD-CODE", snapshot_at_utc=NOW) == (None, "catalogue_conflict")
    assert ProductSKUAlias.objects.get(alias_code="OLD-CODE").alias_code == "OLD-CODE"
    assert competing.sku_code == "OLD-CODE"


def test_sales_backfill_uses_store_and_business_date_and_keeps_source_facts():
    import io
    import json
    from django.core.management import call_command
    from tests.test_sales_management import create_order, user_for, grant
    tenant, _, store, _ = create_scope("dated-sales-links")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="DATED-SPU", product_name="Dated")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="DATED-NEW", legacy_sku_code="DATED-OLD")
    actor = user_for(tenant, "dated-link-admin")
    grant(actor, "integrations.manage")
    api_role = Role.objects.create(tenant=tenant, code="integration_admin", name="Integration admin")
    UserRole.objects.create(tenant=tenant, user=actor, role=api_role)
    alias = _alias(sku, "DATED-OLD", NOW - timedelta(days=10), NOW - timedelta(days=2), scope_type="tenant")
    alias.scope_type, alias.store = "store", store
    alias.save()
    identity = ProductSKUAlias.objects.create(tenant=tenant, sku=sku, alias_code="IDENTITY-OLD",
        code_key=code_key("IDENTITY-OLD"), scope_type="tenant", effective_from=NOW,
        source="identity_correction", reason="identity correction", version_no=2)
    items = []
    for suffix, code, at in (("inside", "DATED-OLD", NOW - timedelta(days=5)), ("outside", "DATED-OLD", NOW),
                             ("identity-past", "IDENTITY-OLD", NOW - timedelta(days=365))):
        order = create_order(tenant, store, suffix)
        order.created_at_utc = at
        order.save()
        item = order.items.get()
        item.seller_sku, item.internal_sku, item.internal_spu = code, None, None
        item.save()
        items.append(item)
    before = [item.line_total_amount for item in items]
    output = io.StringIO()
    call_command("link_sales_skus", tenant_id=tenant.pk, actor_id=actor.pk, apply=True, expected_matches=2, stdout=output)
    assert json.loads(output.getvalue())["matched"] == 2
    for item in items:
        item.refresh_from_db()
    assert [item.internal_sku_id for item in items] == [sku.pk, None, sku.pk]
    assert [item.seller_sku for item in items] == ["DATED-OLD", "DATED-OLD", "IDENTITY-OLD"]
    assert [item.line_total_amount for item in items] == before


def test_identity_correction_alias_resolves_across_business_dates_in_inventory():
    tenant, _, _, warehouse = create_scope("sku-identity-alias")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="IDENTITY-SPU", product_name="Identity")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="CURRENT", legacy_sku_code="OLD-IDENTITY")
    ProductSKUAlias.objects.create(tenant=tenant, sku=sku, alias_code="OLD-IDENTITY",
        code_key=code_key("OLD-IDENTITY"), scope_type="tenant", effective_from=NOW,
        source="identity_correction", reason="controlled identity correction", version_no=1)
    past = NOW - timedelta(days=365)
    assert resolve_inventory_sku(tenant=tenant, warehouse=warehouse, source_sku="OLD-IDENTITY",
        seller_sku="OLD-IDENTITY", snapshot_at_utc=past) == (sku.id, "exact_catalogue_code")
    assert resolve_inventory_skus(tenant=tenant, warehouse=warehouse, sku_pairs=[
        ("OLD-IDENTITY", "OLD-IDENTITY", past),
    ])[("OLD-IDENTITY", "OLD-IDENTITY", past)] == (sku.id, "exact_catalogue_code")
