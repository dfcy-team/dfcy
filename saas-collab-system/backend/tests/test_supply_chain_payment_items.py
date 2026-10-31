import pytest
from rest_framework.test import APIClient
from apps.supply_chain.models import BusinessEvent, PaymentItem
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import internal_user, world

BASE = "/api/internal/supply-chain/v2/settings/payment-items/"

def api(user):
    client = APIClient(); client.force_authenticate(user=user); return client

def payload(**changes):
    return {"name":"清关费", "party_type":"carrier", "default_nature":"corporate", "counts_as_cost":True,
        "default_allocation":"volume", "is_active":True, "sort_order":1, "expected_version":0,
        "reason":"配置测试", **changes}

@pytest.mark.django_db
def test_get_is_read_only_and_managed_initializer_creates_carrier_defaults(world):
    user=internal_user(world); client=api(user)
    assert client.get(BASE).status_code == 200
    assert not PaymentItem.objects.filter(tenant=world["tenant"]).exists()
    response=client.post(BASE+"initialize/")
    assert response.status_code == 200
    rows=list(PaymentItem.objects.filter(tenant=world["tenant"]).order_by("sort_order"))
    assert [x.name for x in rows] == ["报关费","拖车费","国际海运费","港杂费","海外清关费"]
    assert all(x.party_type == "carrier" for x in rows)
    assert [x.default_nature for x in rows] == ["corporate"]*4+["personal"]

@pytest.mark.django_db
def test_create_replay_payload_conflict_patch_version_and_tenant_404(world):
    user=internal_user(world); client=api(user)
    headers={"HTTP_IDEMPOTENCY_KEY":"item-create-1"}
    first=client.post(BASE, payload(), format="json", **headers)
    assert first.status_code == 200
    replay=client.post(BASE, payload(), format="json", **headers)
    assert replay.status_code == 200 and replay.data["data"]["id"] == first.data["data"]["id"]
    changed=client.post(BASE, payload(name="另一项目"), format="json", **headers)
    assert changed.status_code == 422
    item_id=first.data["data"]["id"]
    patch={**payload(expected_version=1), "name":"清关服务"}
    saved=client.patch(f"{BASE}{item_id}/", patch, format="json", HTTP_IDEMPOTENCY_KEY="item-update-1")
    assert saved.status_code == 200 and saved.data["data"]["version"] == 2
    stale=client.patch(f"{BASE}{item_id}/", patch, format="json", HTTP_IDEMPOTENCY_KEY="item-update-2")
    assert stale.status_code == 400
    assert client.patch(f"{BASE}999999/", patch, format="json", HTTP_IDEMPOTENCY_KEY="item-update-3").status_code == 404
    assert client.get(f"{BASE}{item_id}/").status_code == 405
    assert BusinessEvent.objects.filter(aggregate_type="paymentitem", action="payment_item_updated").count() == 2

@pytest.mark.django_db
def test_tenant_isolation_view_only_write_denied_and_deactivation(world):
    user=internal_user(world); client=api(user)
    created=client.post(BASE, payload(name="租户A项目"), format="json", HTTP_IDEMPOTENCY_KEY="tenant-a-item")
    item_id=created.data["data"]["id"]
    other=Tenant.objects.create(name="Other tenant", code="other-payment-tenant")
    other_world={"tenant":other}
    other_user=internal_user(other_world, username="other-payment-user")
    with __import__("apps.supply_chain.models", fromlist=["domain_write"]).domain_write():
        foreign=PaymentItem.objects.create(tenant=other, created_by=other_user, **{k:v for k,v in payload(name="Foreign").items() if k not in ("expected_version","reason")})
    visible=client.get(BASE).data["data"]["items"]
    assert [x["id"] for x in visible] == [item_id]
    assert client.patch(f"{BASE}{foreign.pk}/", {**payload(expected_version=1),"name":"nope"}, format="json", HTTP_IDEMPOTENCY_KEY="tenant-cross").status_code == 404
    readonly=internal_user(world, username="payment-view-only", codes=("supply.v2.view",))
    read_client=api(readonly)
    assert read_client.get(BASE).status_code == 200
    assert read_client.post(BASE+"initialize/").status_code == 403
    assert read_client.post(BASE, payload(), format="json", HTTP_IDEMPOTENCY_KEY="view-write").status_code == 403
    disabled=client.patch(f"{BASE}{item_id}/", {**payload(expected_version=1,name="租户A项目",is_active=False)}, format="json", HTTP_IDEMPOTENCY_KEY="deactivate-item")
    assert disabled.status_code == 200 and disabled.data["data"]["is_active"] is False
