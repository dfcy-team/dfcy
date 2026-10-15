"""MySQL row-lock coverage for concurrent tenant numbering allocation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.accounts.models import CustomUser
from apps.supply_chain.models import DocumentNumberRule, PurchaseOrder, domain_write
from tests.test_supply_chain_v2_foundation import internal_user, world


pytestmark = [pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "mysql", reason="Requires real MySQL row locks.")]
BASE = "/api/internal/supply-chain/v2/"


def _create(user_id, body, key, barrier):
    from rest_framework.test import APIClient
    close_old_connections()
    try:
        user = CustomUser.objects.get(pk=user_id)
        api = APIClient()
        api.force_authenticate(user=user)
        barrier.wait(timeout=20)
        response = api.post(BASE + "purchase-orders/", body, format="json", HTTP_IDEMPOTENCY_KEY=key)
        return response.status_code, response.data
    finally:
        close_old_connections()


def test_mysql_concurrent_document_numbers_are_distinct(world):
    actor = internal_user(world, "number-racer")
    with domain_write():
        DocumentNumberRule.objects.create(tenant=world["tenant"], created_by=actor,
            kind="purchase_order", enabled=True, include_country=True, country_prefixes={},
            prefix="PO", date_format="YYYYMMDD", separator="-", sequence_width=4, reset_period="day")
    body = {"supplier_id": world["supplier"].pk, "country_id": world["country"].pk,
        "lines": [{"sku_id": world["sku"].pk, "quantity": 1, "unit_price": "1.00"}]}
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_create, actor.pk, body, key, barrier) for key in ("number-a", "number-b")]
        responses = [future.result(timeout=60) for future in futures]
    assert [status for status, _ in responses] == [201, 201], responses
    numbers = {payload["data"]["number"] for _, payload in responses}
    assert len(numbers) == 2
    assert sorted(number[-4:] for number in numbers) == ["0001", "0002"]
    assert PurchaseOrder.objects.filter(tenant=world["tenant"], number__in=numbers).count() == 2
