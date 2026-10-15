"""Validate source status while deriving sample cost status from the ledger."""
import pytest
from rest_framework.exceptions import ValidationError
from apps.influencers.tests.test_import_compatibility import sample_records
from apps.influencers.tests.test_historical_values_preservation import _call, _counts

pytestmark = pytest.mark.django_db


def item(status):
    return dict(site_code="PH", requested_sku="SYN-PENDING", product_name="Synthetic",
                quantity=1, unit_cost=None, cost_amount=None, currency="",
                cost_match_status=status)


@pytest.mark.parametrize("status", ["pending", "source"])
def test_source_status_validated_but_ledger_match_status_persisted_and_replayed(sample_records, status):
    result = _call(sample_records, item=item(status))
    saved = result['fulfillment'].items.get()
    assert saved.cost_match_status == 'not_found'
    assert saved.cost_source == 'product_cost_version_unmatched'
    assert saved.cost_amount is None
    before = _counts(sample_records)
    replay = _call(sample_records, item=item(status))
    assert replay['created'] is False
    assert _counts(sample_records) == before


@pytest.mark.parametrize("status", [None, "", "matched"])
def test_invalid_status_rolls_back(sample_records, status):
    before = _counts(sample_records)
    with pytest.raises(ValidationError):
        _call(sample_records, item=item(status))
    assert _counts(sample_records) == before


def test_changed_status_replay_rejected(sample_records):
    result = _call(sample_records, item=item('pending'))
    before = _counts(sample_records)
    with pytest.raises(ValidationError):
        _call(sample_records, item=item('source'))
    assert _counts(sample_records) == before
    assert result['fulfillment'].items.get().cost_match_status == 'not_found'
