import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError as APIValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.supply_chain.warehouse_archives import (
    WarehouseArchiveDetail, WarehouseArchives, can_maintain_warehouse,
    save_warehouse_archive, warehouse_archive_data, warehouse_refs,
)
from tests.test_supply_chain_v2_foundation import internal_user, supplier_user, world


def call_view(view, user, method, path, data=None, *, key=None, pk=None):
    factory = APIRequestFactory()
    kwargs = {"format": "json"}
    if key:
        kwargs["HTTP_IDEMPOTENCY_KEY"] = key
    request = getattr(factory, method)(path, data or {}, **kwargs)
    force_authenticate(request, user=user)
    response = view.as_view()(request, **({"pk": pk} if pk else {}))
    response.render()
    return response


@pytest.mark.django_db
def test_warehouse_archive_metadata_version_replay_and_wms_identity_is_unchanged(world):
    actor = internal_user(world, "warehouse-manager")
    warehouse = WarehouseMaster.objects.create(tenant=world["tenant"], code="local-us", name="US Warehouse",
        country_code="US", warehouse_type="owned", legacy_codes=["FEISHU-OLD"])
    config = PlatformIntegrationConfig.objects.create(tenant=world["tenant"], platform="jifeng_wms",
        account_alias="warehouse-test", created_by=actor)
    mapping = WarehouseAuthorization.objects.create(tenant=world["tenant"], integration_config=config,
        warehouse=warehouse, provider="jifeng_wms", external_warehouse_code="WMS-007",
        external_warehouse_region="US", credential_id="opaque-credential", status=WarehouseAuthorization.Status.ACTIVE,
        created_by=actor, updated_by=actor)
    authorized_mapping = WarehouseAuthorization.objects.create(tenant=world["tenant"], integration_config=config,
        warehouse=warehouse, provider="other_wms", external_warehouse_code="WMS-008",
        external_warehouse_region="CA", credential_id="opaque-credential-2", status="authorized",
        created_by=actor, updated_by=actor)

    payload = {"expected_version": 1, "address": "Dock 4", "region": "West", "legacy_codes": ["FEISHU-OLD", " FEISHU-2 ", "FEISHU-2"], "notes": "Receiving"}
    saved = save_warehouse_archive(actor, payload, pk=warehouse.pk, idempotency_key="warehouse-update-1")
    assert saved.supply_version == 2
    assert saved.legacy_codes == ["FEISHU-OLD", "FEISHU-2"]
    replay = save_warehouse_archive(actor, payload, pk=warehouse.pk, idempotency_key="warehouse-update-1")
    assert replay.pk == saved.pk and replay.supply_version == 2
    view = warehouse_archive_data(saved, actor)
    assert view["wms_mappings"] == [
        {"provider": "jifeng_wms", "external_warehouse_code": "WMS-007", "external_warehouse_region": "US", "status": mapping.status},
        {"provider": "other_wms", "external_warehouse_code": "WMS-008", "external_warehouse_region": "CA", "status": authorized_mapping.status},
    ]
    mapping.refresh_from_db()
    assert (mapping.provider, mapping.external_warehouse_code, mapping.external_warehouse_region) == ("jifeng_wms", "WMS-007", "US")
    assert not any("credential" in key or "token" in key or "email" in key or "config" in key for key in view["wms_mappings"][0])

    with pytest.raises(DjangoValidationError):
        save_warehouse_archive(actor, {**payload, "address": "Changed"}, pk=warehouse.pk, idempotency_key="warehouse-replay-conflict")
    with pytest.raises(DjangoValidationError):
        save_warehouse_archive(actor, {"expected_version": 1, "notes": "stale"}, pk=warehouse.pk, idempotency_key="warehouse-stale")


@pytest.mark.django_db
def test_warehouse_archive_scopes_alias_validation_and_forbidden_identity_fields(world):
    warehouse = WarehouseMaster.objects.create(tenant=world["tenant"], code="visible", name="Visible", country_code="US", warehouse_type="owned")
    other_tenant = type(world["tenant"]).objects.create(name="other warehouse tenant", code="other-warehouse-tenant")
    hidden = WarehouseMaster.objects.create(tenant=other_tenant, code="hidden", name="Hidden", country_code="CA", warehouse_type="owned")

    custom = internal_user(world, "warehouse-custom", scope=DataScope.ScopeType.CUSTOM, config={"warehouse_ids": [warehouse.pk]})
    assert list(warehouse_refs(custom).values_list("pk", flat=True)) == [warehouse.pk]
    assert can_maintain_warehouse(custom, warehouse.pk)
    assert not can_maintain_warehouse(custom)
    assert not warehouse_refs(internal_user(world, "warehouse-other-tenant")).filter(pk=hidden.pk).exists()
    all_scope_actor = internal_user(world, "warehouse-tenant-manager")
    assert not can_maintain_warehouse(all_scope_actor, hidden.pk)
    external = supplier_user(world, world["supplier"], "external-warehouse-user")
    with pytest.raises(PermissionDenied):
        warehouse_refs(external)

    own = internal_user(world, "warehouse-own-scope", scope=DataScope.ScopeType.OWN)
    supplier_only = internal_user(world, "warehouse-supplier-scope", scope=DataScope.ScopeType.CUSTOM, config={"supplier_ids": [123]})
    assert warehouse_refs(own).filter(pk=warehouse.pk).exists() and not can_maintain_warehouse(own, warehouse.pk)
    assert warehouse_refs(supplier_only).filter(pk=warehouse.pk).exists() and not can_maintain_warehouse(supplier_only, warehouse.pk)

    bad_scope = internal_user(world, "warehouse-invalid-scope", scope=DataScope.ScopeType.CUSTOM, config={"warehouse_ids": "malformed"})
    with pytest.raises(PermissionDenied):
        warehouse_refs(bad_scope)

    response = call_view(WarehouseArchiveDetail, custom, "patch", f"/api/internal/supply-chain/v2/warehouses/{warehouse.pk}/",
        {"expected_version": 1, "legacy_codes": {"unexpected": "dict"}}, key="invalid-alias", pk=warehouse.pk)
    assert response.status_code == 400
    response = call_view(WarehouseArchiveDetail, custom, "patch", f"/api/internal/supply-chain/v2/warehouses/{warehouse.pk}/",
        {"expected_version": 1, "api_token": "secret", "notes": "bad"}, key="forbidden-identity", pk=warehouse.pk)
    assert response.status_code == 400
    with pytest.raises(APIValidationError):
        save_warehouse_archive(custom, {"expected_version": 1, "legacy_codes": ["x" * 121]}, pk=warehouse.pk, idempotency_key="oversized-alias")


@pytest.mark.django_db
def test_warehouse_archive_list_searches_legacy_aliases_and_shows_create_scope(world):
    actor = internal_user(world, "warehouse-all")
    WarehouseMaster.objects.create(tenant=world["tenant"], code="sys-code", name="Archive name", country_code="US",
        warehouse_type="owned", legacy_codes=["LEGACY-CODE-99"])
    response = call_view(WarehouseArchives, actor, "get", "/api/internal/supply-chain/v2/warehouses/", key=None)
    assert response.status_code == 200
    response = call_view(WarehouseArchives, actor, "get", "/api/internal/supply-chain/v2/warehouses/?search=LEGACY-CODE-99")
    assert response.status_code == 200
    assert response.data["count"] == 1 and response.data["data"][0]["code"] == "sys-code"
