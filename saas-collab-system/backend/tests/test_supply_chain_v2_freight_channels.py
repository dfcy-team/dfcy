from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope
from apps.supply_chain import freight_channels, services
from apps.supply_chain.cost_models import FeeRecord
from apps.supply_chain.models import DispatchBatch, DispatchMembership, FreightCompany, FreightQuote, domain_write
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import (
    confirmed_order, freight, internal_user, po_payload, shipment_payload, world,
)

BASE = "/api/internal/supply-chain/v2/"


def api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def write(client, path, body, key, method="post"):
    return getattr(client, method)(BASE + path, body, format="json", HTTP_IDEMPOTENCY_KEY=key)


def channel_body(carrier, country, code):
    return {"company_id": carrier.pk, "country_id": country.pk, "code": code,
            "name": f"{code} sea", "origin": "Shanghai", "cargo_type": "general",
            "transport_mode": "sea", "notes": "research channel"}


def quote_body(day, *, basis="cbm", price="100", tax="10", includes_tax=False, ends=None, reason="rate update"):
    return {"expected_channel_version": 1, "effective_from": day.isoformat(),
            "effective_to": ends.isoformat() if ends else None, "billing_basis": basis,
            "fee_per_cbm": price if basis == "cbm" else None,
            "container_fee": price if basis == "container" else None,
            "container_type": "40HQ" if basis == "container" else "", "tax_percent": tax,
            "prices_include_tax": includes_tax, "notes": "quote note", "reason": reason}


def create_batch(user, channel, quote, shipment, carrier, *, count=1, key="batch"):
    client = api(user)
    response = write(client, "dispatch-batches/", {
        "shipment_ids": [shipment.pk], "shipment_versions": [{"id": shipment.pk, "version": shipment.version}],
        "freight_company_id": carrier.pk, "freight_number": f"F-{key}",
        "freight_channel_id": channel.pk, "freight_quote_id": quote.pk,
        "container_count": count,
    }, key)
    assert response.status_code == 201, response.data
    return DispatchBatch.objects.get(pk=response.data["data"]["id"])


@pytest.mark.django_db
def test_channels_are_tenant_scoped_country_specific_and_quotes_are_append_only(world):
    buyer = internal_user(world, "freight-buyer")
    carrier = freight(world)
    today = timezone.localdate()
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        client = api(buyer)
        us = client.post(BASE + "freight-channels/", channel_body(carrier, world["country"], "us-sea"),
                         format="json", HTTP_IDEMPOTENCY_KEY="us-channel")
        ca = client.post(BASE + "freight-channels/", channel_body(carrier, world["country_ca"], "ca-sea"),
                         format="json", HTTP_IDEMPOTENCY_KEY="ca-channel")
        assert us.status_code == ca.status_code == 201
        us_id, ca_id = us.data["data"]["id"], ca.data["data"]["id"]
        first = write(client, f"freight-channels/{us_id}/quotes/", quote_body(today, price="80"), "us-q1")
        assert first.status_code == 201, first.data
        future = write(client, f"freight-channels/{us_id}/quotes/", {
            **quote_body(today + timedelta(days=10), price="90"), "expected_channel_version": 2,
        }, "us-future")
        assert future.status_code == 201, future.data
        current = client.get(BASE + f"freight-channels/{us_id}/quotes/").data["data"]
        assert [row["sequence"] for row in current] == [2, 1]
        current_channel = client.get(BASE + "freight-channels/?company_id=%s" % carrier.pk).data["data"]
        assert next(row for row in current_channel if row["id"] == us_id)["current_quote"]["sequence"] == 1
        detail = client.get(BASE + "freight-channels/?active=true&country_code=CA").data["data"]
        assert [row["id"] for row in detail] == [ca_id]
        assert client.get(BASE + f"freight-channels/{us_id}/").status_code == 405

        # The later, already effective quote expires; an older open-ended quote must not revive.
        expired = write(client, f"freight-channels/{us_id}/quotes/", {
            **quote_body(today - timedelta(days=2), price="95", ends=today - timedelta(days=1)),
            "expected_channel_version": 3,
        }, "us-expired")
        assert expired.status_code == 201, expired.data
        listed = client.get(BASE + "freight-channels/?company_id=%s" % carrier.pk).data["data"]
        assert next(row for row in listed if row["id"] == us_id)["current_quote"] is None

    readonly = api(internal_user(world, "freight-reader", codes=("supply.v2.view",)))
    assert readonly.get(BASE + "freight-channels/").status_code == 200
    denied = write(readonly, "freight-channels/", channel_body(carrier, world["country"], "read-only"), "readonly")
    assert denied.status_code == 403


@pytest.mark.django_db
def test_quote_publish_replay_staleness_and_immutable_history(world):
    buyer = internal_user(world, "freight-replay")
    carrier = freight(world)
    today = timezone.localdate()
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        c = api(buyer)
        channel_response = c.post(BASE + "freight-channels/", channel_body(carrier, world["country"], "replay"),
                                  format="json", HTTP_IDEMPOTENCY_KEY="replay-channel")
        assert channel_response.status_code == 201, channel_response.data
        channel_id = channel_response.data["data"]["id"]
        body = quote_body(today, price="88")
        first = write(c, f"freight-channels/{channel_id}/quotes/", body, "quote-replay")
        assert first.status_code == 201, first.data
        quote_id = first.data["data"]["id"]
        repeated = write(c, f"freight-channels/{channel_id}/quotes/", body, "quote-replay")
        assert repeated.status_code == 201, repeated.data
        assert repeated.data["data"]["id"] == quote_id
        channel_response = c.get(BASE + "freight-channels/?company_id=%s" % carrier.pk).data["data"]
        assert next(row for row in channel_response if row["id"] == channel_id)["version"] == 2
        assert FreightQuote.objects.filter(channel_id=channel_id).count() == 1

        changed_same_key = write(c, f"freight-channels/{channel_id}/quotes/", {
            **body, "notes": "different content",
        }, "quote-replay")
        assert changed_same_key.status_code == 422
        stale_version = write(c, f"freight-channels/{channel_id}/quotes/", {
            **body, "reason": "stale attempt",
        }, "quote-stale")
        assert stale_version.status_code == 422
        assert FreightQuote.objects.filter(channel_id=channel_id).count() == 1

        quote = FreightQuote.objects.get(pk=quote_id)
        quote.notes = "attempted overwrite"
        with pytest.raises(DjangoValidationError, match="不能覆盖"):
            quote.save()
        quote.refresh_from_db()
        assert quote.notes == "quote note"


@pytest.mark.django_db
def test_channel_listing_and_quote_publication_are_tenant_isolated(world):
    buyer = internal_user(world, "freight-tenant-owner")
    carrier = freight(world)
    today = timezone.localdate()
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        owner = api(buyer)
        channel_response = owner.post(BASE + "freight-channels/", channel_body(carrier, world["country"], "private"),
                                      format="json", HTTP_IDEMPOTENCY_KEY="private-channel")
        assert channel_response.status_code == 201, channel_response.data
        channel_id = channel_response.data["data"]["id"]

        foreign_tenant = Tenant.objects.create(name="freight-foreign", code="freight-foreign")
        foreign_world = {**world, "tenant": foreign_tenant}
        foreign_user = internal_user(foreign_world, "freight-foreign-user")
        foreign = api(foreign_user)
        listed = foreign.get(BASE + "freight-channels/")
        assert listed.status_code == 200
        assert all(row["id"] != channel_id for row in listed.data["data"])
        foreign_publish = write(foreign, f"freight-channels/{channel_id}/quotes/", quote_body(today), "foreign-publish")
        assert foreign_publish.status_code == 404
        assert not FreightQuote.objects.filter(channel_id=channel_id).exists()


@pytest.mark.django_db
def test_dispatch_rejects_mismatched_country_company_channel_and_superseded_quote_without_writes(world):
    buyer = internal_user(world, "freight-selection-guards")
    carrier = freight(world)
    today = timezone.localdate()
    client = api(buyer)
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        us_response = client.post(BASE + "freight-channels/", channel_body(carrier, world["country"], "guard-us"),
                                  format="json", HTTP_IDEMPOTENCY_KEY="guard-us-channel")
        ca_response = client.post(BASE + "freight-channels/", channel_body(carrier, world["country_ca"], "guard-ca"),
                                  format="json", HTTP_IDEMPOTENCY_KEY="guard-ca-channel")
        assert us_response.status_code == ca_response.status_code == 201
        us_id, ca_id = us_response.data["data"]["id"], ca_response.data["data"]["id"]
        us_q1 = write(client, f"freight-channels/{us_id}/quotes/", quote_body(today, price="100"), "guard-us-q1")
        ca_quote = write(client, f"freight-channels/{ca_id}/quotes/", quote_body(today, price="120"), "guard-ca-q1")
        assert us_q1.status_code == ca_quote.status_code == 201
        us_q2 = write(client, f"freight-channels/{us_id}/quotes/", {
            **quote_body(today, price="110"), "expected_channel_version": 2,
        }, "guard-us-q2")
        assert us_q2.status_code == 201, us_q2.data

    with domain_write():
        other_carrier = FreightCompany.objects.create(tenant=world["tenant"], created_by=buyer,
            code="other-carrier", name="Other carrier")
    us_order = confirmed_order(world, buyer, key="guard-us-order", payload=po_payload(world, number="PO-GUARD-US"))
    ca_order = confirmed_order(world, buyer, key="guard-ca-order", payload=po_payload(
        world, number="PO-GUARD-CA", country=world["country_ca"],
    ))
    us_shipment = services.create_supplier_shipment(buyer, shipment_payload(world, us_order, "guard-us-shipment"),
                                                    idempotency_key="guard-us-shipment")
    ca_shipment = services.create_supplier_shipment(buyer, shipment_payload(world, ca_order, "guard-ca-shipment", number="SH-GUARD-CA"),
                                                    idempotency_key="guard-ca-shipment")
    initial_batches = DispatchBatch.objects.count()
    initial_memberships = DispatchMembership.objects.count()
    cases = [
        # A US shipment cannot select the same carrier's Canada channel.
        (us_shipment, carrier, ca_id, ca_quote.data["data"]["id"]),
        # A quote from another country cannot be paired with the US channel.
        (us_shipment, carrier, us_id, ca_quote.data["data"]["id"]),
        # An older quote is stale once a newer applicable version is published.
        (us_shipment, carrier, us_id, us_q1.data["data"]["id"]),
        # A channel cannot be attached to another carrier.
        (us_shipment, other_carrier, us_id, us_q2.data["data"]["id"]),
        # The inverse country pairing is rejected too.
        (ca_shipment, carrier, us_id, us_q2.data["data"]["id"]),
    ]
    client = api(buyer)
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        for index, (shipment, selected_carrier, channel_id, quote_id) in enumerate(cases):
            response = write(client, "dispatch-batches/", {
                "shipment_ids": [shipment.pk],
                "shipment_versions": [{"id": shipment.pk, "version": shipment.version}],
                "freight_company_id": selected_carrier.pk, "freight_number": f"GUARD-{index}",
                "freight_channel_id": channel_id, "freight_quote_id": quote_id,
            }, f"guard-batch-{index}")
            assert response.status_code == 422, response.data
    assert DispatchBatch.objects.count() == initial_batches
    assert DispatchMembership.objects.count() == initial_memberships


@pytest.mark.django_db
def test_dispatch_freezes_selected_quote_and_explicit_adoption_updates_reference_without_fee_record(world):
    buyer = internal_user(world, "freight-snapshot")
    carrier = freight(world)
    order = confirmed_order(world, buyer, key="freight-order", payload=po_payload(world, number="PO-FREIGHT"))
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, "freight-shipment"),
                                                 idempotency_key="freight-shipment")
    today = timezone.localdate()
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        c = api(buyer)
        created = c.post(BASE + "freight-channels/", channel_body(carrier, world["country"], "freeze-me"),
                         format="json", HTTP_IDEMPOTENCY_KEY="snapshot-channel")
        assert created.status_code == 201, created.data
        channel_id = created.data["data"]["id"]
        q1 = write(c, f"freight-channels/{channel_id}/quotes/", quote_body(today, price="100"), "snapshot-q1")
        assert q1.status_code == 201, q1.data
        quote1 = q1.data["data"]
        batch = create_batch(buyer, type("Channel", (), {"pk": channel_id})(), type("Quote", (), {"pk": quote1["id"]})(), shipment, carrier, count=2, key="freeze")
        original_snapshot = batch.freight_quote_snapshot
        assert original_snapshot["quote"]["sequence"] == 1
        assert freight_channels.freight_reference(batch, chargeable_cbm=Decimal("3"))["reference_amount"] == "330.00"
        assert not FeeRecord.objects.filter(batch=batch).exists()

        q2 = write(c, f"freight-channels/{channel_id}/quotes/", {
            **quote_body(today, price="200", tax="0"), "expected_channel_version": 2,
        }, "snapshot-q2")
        assert q2.status_code == 201, q2.data
        response = write(c, f"dispatch-batches/{batch.pk}/", {
            "expected_version": batch.version, "notes": "metadata only",
        }, "snapshot-notes", "patch")
        assert response.status_code == 200, response.data
        batch.refresh_from_db()
        assert batch.freight_quote_snapshot == original_snapshot
        assert not FeeRecord.objects.filter(batch=batch).exists()

        adopted = write(c, f"dispatch-batches/{batch.pk}/", {
            "expected_version": batch.version, "freight_channel_id": channel_id,
            "freight_quote_id": q2.data["data"]["id"],
        }, "snapshot-adopt", "patch")
        assert adopted.status_code == 200, adopted.data
        batch.refresh_from_db()
        assert batch.freight_quote_snapshot["quote"]["sequence"] == 2
        assert freight_channels.freight_reference(batch, chargeable_cbm=Decimal("3"))["reference_amount"] == "600.00"
        assert not FeeRecord.objects.filter(batch=batch).exists()


@pytest.mark.django_db
def test_quote_reference_supports_tax_inclusive_container_billing(world):
    buyer = internal_user(world, "freight-container")
    carrier = freight(world)
    order = confirmed_order(world, buyer, key="container-order", payload=po_payload(world, number="PO-CONTAINER"))
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, "container-shipment"),
                                                 idempotency_key="container-shipment")
    today = timezone.localdate()
    with patch("apps.supply_chain.freight_channels.business_date", return_value=today):
        c = api(buyer)
        channel = c.post(BASE + "freight-channels/", channel_body(carrier, world["country"], "container-rate"),
                         format="json", HTTP_IDEMPOTENCY_KEY="container-channel")
        assert channel.status_code == 201, channel.data
        channel_id = channel.data["data"]["id"]
        quote = write(c, f"freight-channels/{channel_id}/quotes/", quote_body(today, basis="container", price="75", tax="10", includes_tax=True), "container-q")
        assert quote.status_code == 201, quote.data
        batch = create_batch(buyer, type("Channel", (), {"pk": channel_id})(), type("Quote", (), {"pk": quote.data["data"]["id"]})(), shipment, carrier, count=2, key="container-batch")
        reference = freight_channels.freight_reference(batch)
        assert reference["billing_basis"] == "container"
        assert reference["quantity"] == "2"
        assert reference["reference_amount"] == "150.00"
        assert reference["prices_include_tax"] is True
