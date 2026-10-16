import pytest
from datetime import date
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.audit.models import OperationLog
from apps.masterdata.models import SupplierMaster
from apps.purchasing.models import PurchaseOrder as LegacyPurchaseOrder
from apps.suppliers.models import SupplierPerformanceSnapshot, SupplierTask
from apps.supply_chain.models import FreightCompany, domain_write
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_ui_p2_system_masterdata import client_for, create_user, grant


pytestmark = pytest.mark.django_db
BASE = "/api/internal/supply-chain/v2/"


def api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_masterdata_supplier_delete_succeeds_and_audits():
    tenant = Tenant.objects.create(code="supplier-delete", name="Supplier delete")
    user = create_user(tenant, "supplier-delete-manager")
    grant(user, "masterdata.manage")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="unused", name="Unused")

    response = client_for(user).delete(f"/api/internal/master-data/suppliers/{supplier.pk}/")

    assert response.status_code == 200
    assert not SupplierMaster.objects.filter(pk=supplier.pk).exists()
    assert OperationLog.objects.filter(tenant=tenant, action="delete", object_id=str(supplier.pk)).exists()


@pytest.mark.parametrize("status", SupplierTask.Status.values)
def test_masterdata_supplier_delete_blocks_task_in_every_status(status):
    tenant = Tenant.objects.create(code=f"supplier-task-{status}", name="Supplier task")
    user = create_user(tenant, f"supplier-task-manager-{status}")
    grant(user, "masterdata.manage")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="used", name="Used")
    task = SupplierTask.objects.create(
        tenant=tenant, supplier_id=supplier.pk, task_no=f"task-{status}", sku_code="SKU", status=status,
    )

    response = client_for(user).delete(f"/api/internal/master-data/suppliers/{supplier.pk}/")

    assert response.status_code == 409
    assert "停用" in response.data["message"]
    assert SupplierMaster.objects.filter(pk=supplier.pk).exists()
    assert SupplierTask.objects.filter(pk=task.pk).exists()


def test_supply_supplier_delete_checks_permissions_tenant_and_legacy_references(world):
    user = internal_user(world, "supplier-delete-v2")
    supplier = world["supplier"]
    client = api(user)

    deleted = client.delete(BASE + f"suppliers/{world['supplier_b'].pk}/")
    assert deleted.status_code == 200, deleted.data
    assert not SupplierMaster.objects.filter(pk=world["supplier_b"].pk).exists()

    SupplierTask.objects.create(tenant=world["tenant"], supplier_id=supplier.pk,
                                task_no="used-task", sku_code="SKU", status=SupplierTask.Status.CANCELLED)
    conflict = client.delete(BASE + f"suppliers/{supplier.pk}/")
    assert conflict.status_code == 409
    assert "停用" in conflict.data["message"]
    assert SupplierMaster.objects.filter(pk=supplier.pk).exists()

    other = Tenant.objects.create(code="supplier-delete-outsider", name="Outsider")
    outsider_world = {"tenant": other}
    outsider = internal_user(outsider_world, "supplier-delete-outsider")
    assert api(outsider).delete(BASE + f"suppliers/{supplier.pk}/").status_code == 404


def test_deleted_supplier_idempotency_replay_returns_not_found_without_recreating(world):
    user = internal_user(world, "supplier-deleted-replay", codes=("supply.v2.view", "supply.v2.manage"))
    client = api(user)
    payload = {"code": "MANUAL-REPLAY", "name": "Manual replay supplier"}
    key = "manual-supplier-deleted-replay"

    created = client.post(BASE + "suppliers/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert created.status_code == 201, created.data
    supplier_id = created.data["data"]["id"]

    deleted = client.delete(BASE + f"suppliers/{supplier_id}/")
    assert deleted.status_code == 200, deleted.data

    replay = client.post(BASE + "suppliers/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert replay.status_code == 404, replay.data
    assert not SupplierMaster.objects.filter(pk=supplier_id).exists()
    assert not SupplierMaster.objects.filter(tenant=world["tenant"], code="MANUAL-REPLAY").exists()


@pytest.mark.parametrize("endpoint", ["masterdata", "supply"])
@pytest.mark.parametrize("reference", ["purchase_order", "external_profile", "performance_snapshot"])
def test_supplier_delete_blocks_additional_non_fk_business_references(endpoint, reference):
    tenant = Tenant.objects.create(code=f"supplier-ref-{endpoint}-{reference}", name="Supplier reference")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="referenced", name="Referenced")
    if endpoint == "masterdata":
        user = create_user(tenant, f"supplier-ref-manager-{reference}")
        grant(user, "masterdata.manage")
        client = client_for(user)
        url = f"/api/internal/master-data/suppliers/{supplier.pk}/"
    else:
        user = internal_user({"tenant": tenant}, f"supplier-ref-v2-{reference}")
        client = api(user)
        url = BASE + f"suppliers/{supplier.pk}/"

    if reference == "purchase_order":
        LegacyPurchaseOrder.objects.create(
            tenant=tenant, po_no="LEGACY-PO", sku_code="SKU", supplier_id=supplier.pk,
            quantity=1, unit_price="1.00", created_by=user,
        )
    elif reference == "external_profile":
        external = CustomUser.objects.create_user(
            username=f"external-{endpoint}-{reference}", tenant=tenant,
            user_type=CustomUser.UserType.EXTERNAL,
        )
        ExternalUserProfile.objects.create(user=external, tenant=tenant, supplier_id=supplier.pk)
    else:
        SupplierPerformanceSnapshot.objects.create(
            tenant=tenant, supplier_id=supplier.pk, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )

    response = client.delete(url)

    assert response.status_code == 409, response.data
    assert "停用" in response.data["message"]
    assert SupplierMaster.objects.filter(pk=supplier.pk).exists()


def test_freight_delete_succeeds_and_blocks_channel_references(world):
    from apps.supply_chain.freight_models import FreightChannel

    user = internal_user(world, "freight-delete")
    with domain_write():
        unused = FreightCompany.objects.create(
            tenant=world["tenant"], created_by=user, code="unused-carrier", name="Unused carrier",
        )
        referenced = FreightCompany.objects.create(
            tenant=world["tenant"], created_by=user, code="used-carrier", name="Used carrier",
        )
        channel = FreightChannel.objects.create(
            tenant=world["tenant"], created_by=user, company=referenced, country=world["country"],
            code="used-channel", name="Used channel", origin="Shanghai", cargo_type="general", transport_mode="sea",
        )
    client = api(user)

    deleted = client.delete(BASE + f"freight-companies/{unused.pk}/")
    assert deleted.status_code == 200, deleted.data
    assert not FreightCompany.objects.filter(pk=unused.pk).exists()
    conflict = client.delete(BASE + f"freight-companies/{referenced.pk}/")
    assert conflict.status_code == 409
    assert "停用" in conflict.data["message"]
    assert FreightCompany.objects.filter(pk=referenced.pk).exists()
    assert FreightChannel.objects.filter(pk=channel.pk).exists()

    other = Tenant.objects.create(code="freight-delete-outsider", name="Outsider")
    outsider_world = {"tenant": other}
    outsider = internal_user(outsider_world, "freight-delete-outsider")
    assert api(outsider).delete(BASE + f"freight-companies/{referenced.pk}/").status_code == 404
