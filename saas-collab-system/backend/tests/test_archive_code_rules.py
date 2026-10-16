import pytest
from rest_framework.test import APIClient

from apps.masterdata.models import ArchiveCodeRule, SupplierMaster
from apps.supply_chain.models import FreightCompany
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import internal_user, world


pytestmark = pytest.mark.django_db
SETTINGS = "/api/internal/master-data/archive-code-rules/"
SUPPLY = "/api/internal/supply-chain/v2/"


def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def rules(**changes):
    defaults = [
        {"kind": "supplier", "is_enabled": True, "prefix": "GY", "separator": "", "sequence_width": 3},
        {"kind": "freight", "is_enabled": True, "prefix": "HY", "separator": "-", "sequence_width": 4},
    ]
    for row in defaults:
        row.update(changes.get(row["kind"], {}))
    return defaults


def test_settings_permissions_validation_and_tenant_isolation(world):
    viewer = internal_user(world, "archive-rule-viewer", codes=("masterdata.settings.view",))
    manager = internal_user(world, "archive-rule-manager", codes=("masterdata.settings.view", "masterdata.settings.manage"))
    assert client(viewer).get(SETTINGS).json()["data"]["rules"][0]["is_enabled"] is False
    assert client(viewer).put(SETTINGS, {"rules": rules()}, format="json").status_code == 403
    invalid = rules(supplier={"prefix": "中文"})
    assert client(manager).put(SETTINGS, {"rules": invalid}, format="json").status_code == 400
    assert not ArchiveCodeRule.objects.filter(tenant=world["tenant"]).exists()
    response = client(manager).put(SETTINGS, {"rules": rules()}, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["rules"][1]["preview"] == "HY-0001"
    other = Tenant.objects.create(name="Other archive tenant", code="other-archive-rules")
    assert ArchiveCodeRule.objects.filter(tenant=other).count() == 0


def test_auto_code_skips_existing_codes_and_works_in_both_create_paths(world):
    actor = internal_user(world, "archive-rule-creator", codes=(
        "masterdata.settings.view", "masterdata.settings.manage", "masterdata.view", "masterdata.manage",
        "supply.v2.view", "supply.v2.manage",
    ))
    api = client(actor)
    assert api.put(SETTINGS, {"rules": rules()}, format="json").status_code == 200
    SupplierMaster.objects.create(tenant=world["tenant"], code="GY001", name="Existing")
    first = api.post(SUPPLY + "suppliers/", {"name": "自动供应商"}, format="json", HTTP_IDEMPOTENCY_KEY="auto-supplier")
    assert first.status_code == 201 and first.json()["data"]["code"] == "GY002"
    replay = api.post(SUPPLY + "suppliers/", {"name": "自动供应商"}, format="json", HTTP_IDEMPOTENCY_KEY="auto-supplier")
    assert replay.status_code == 201 and replay.json()["data"]["id"] == first.json()["data"]["id"]
    basic = api.post("/api/internal/master-data/suppliers/", {"name": "基础维护新增"}, format="json")
    assert basic.status_code == 201 and basic.json()["data"]["code"] == "GY003"
    freight = api.post(SUPPLY + "freight-companies/", {"name": "自动货运"}, format="json", HTTP_IDEMPOTENCY_KEY="auto-freight")
    assert freight.status_code == 201 and freight.json()["data"]["code"] == "HY-0001"
    assert FreightCompany.objects.filter(tenant=world["tenant"], code="HY-0001").exists()
    assert ArchiveCodeRule.objects.get(tenant=world["tenant"], kind="supplier").next_sequence == 4


def test_blank_code_requires_enabled_rule_but_manual_code_remains_supported(world):
    actor = internal_user(world, "archive-rule-manual", codes=("supply.v2.view", "supply.v2.manage"))
    api = client(actor)
    missing = api.post(SUPPLY + "freight-companies/", {"name": "没有规则"}, format="json", HTTP_IDEMPOTENCY_KEY="no-rule")
    assert missing.status_code == 400
    manual = api.post(SUPPLY + "freight-companies/", {"code": "FORWARDER-1", "name": "手工编码"}, format="json", HTTP_IDEMPOTENCY_KEY="manual-rule")
    assert manual.status_code == 201 and manual.json()["data"]["code"] == "FORWARDER-1"
