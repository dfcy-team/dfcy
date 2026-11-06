import pytest
from rest_framework.test import APIClient

from apps.supply_chain.cost_models import PaymentApplication, PaymentRecord, SettlementRecord
from apps.supply_chain import services
from apps.supply_chain.models import BusinessEvent
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import internal_user, world


pytestmark = pytest.mark.django_db
PATH = "/api/internal/supply-chain/v2/monthly-payables/shipment-drilldown/"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("42", "SH-1"),
        ('["unexpected", "array"]', "SH-1"),
        ("null", "SH-1"),
        ("ordinary note text", "SH-1"),
        ('{"出库单号":"SRC-001"}', "SRC-001"),
        ('{}', "SH-1"),
    ],
)
def test_drilldown_handles_notes_values_and_preserves_source_number(world, payload, expected):
    buyer, _, shipment = pilot(world, geometry=False)
    shipment.notes = "imported shipment\n" + payload
    with services.domain_write():
        shipment.save(update_fields=["notes"])
    client = APIClient()
    client.force_authenticate(user=buyer)

    counts = (BusinessEvent.objects.count(), PaymentRecord.objects.count(),
              PaymentApplication.objects.count(), SettlementRecord.objects.count())
    response = client.get(PATH, {"shipment_id": shipment.pk, "month": "2026-10"})

    assert response.status_code == 200, response.data
    assert response.data["data"]["shipment"]["source_number"] == expected
    assert (BusinessEvent.objects.count(), PaymentRecord.objects.count(),
            PaymentApplication.objects.count(), SettlementRecord.objects.count()) == counts


def test_drilldown_does_not_expose_foreign_tenant_shipment(world):
    _, _, shipment = pilot(world, geometry=False)
    foreign_world = {**world, "tenant": Tenant.objects.create(code="drill-foreign", name="Foreign")}
    foreign_user = internal_user(foreign_world, username="drill-foreign-user")
    client = APIClient()
    client.force_authenticate(user=foreign_user)

    response = client.get(PATH, {"shipment_id": shipment.pk, "month": "2026-10"})

    assert response.status_code == 404
