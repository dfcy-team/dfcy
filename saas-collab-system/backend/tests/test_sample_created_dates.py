from datetime import datetime

import pytest
from django.db.models.query import QuerySet
from rest_framework.test import APIClient

from apps.influencers.models import SampleFulfillment
from tests.test_bd_performance_sample_only import facts  # noqa: F401

pytestmark = pytest.mark.django_db
URL = '/api/internal/influencers/sample-fulfillments/'


@pytest.fixture
def dated_samples(facts):
    tenant, owner, _, _, make_sample, _ = facts
    owner.is_superuser = True
    owner.save(update_fields=['is_superuser'])
    client = APIClient()
    client.force_authenticate(owner)
    dates = ['2026-07-31T23:59:59+08:00', '2026-08-01T00:00:00+08:00',
             '2026-08-31T23:59:59.999999+08:00', '2026-09-01T00:00:00+08:00']
    for i, value in enumerate(dates):
        row = make_sample(f'DATE-{i}', linked=False)
        QuerySet.update(SampleFulfillment.objects.filter(pk=row.pk), created_at=datetime.fromisoformat(value))
    return client, owner


@pytest.mark.parametrize('params,expected', [
    ({'created_from': '2026-08-01', 'created_to': '2026-08-31'}, {'DATE-1', 'DATE-2'}),
    ({'created_from': '2026-08-01'}, {'DATE-1', 'DATE-2', 'DATE-3'}),
    ({'created_to': '2026-08-31'}, {'DATE-0', 'DATE-1', 'DATE-2'}),
    ({'created_from': '2026-08-31', 'created_to': '2026-08-31'}, {'DATE-2'}),
    ({'created_from': '', 'created_to': ''}, {'DATE-0', 'DATE-1', 'DATE-2', 'DATE-3'}),
])
def test_date_range_uses_created_time_and_inclusive_beijing_days(dated_samples, params, expected):
    client, owner = dated_samples
    result = client.get(URL, {**params, 'owner': owner.pk})
    assert result.status_code == 200
    assert {r['fulfillment_no'] for r in result.data['data']['results']} == expected
    assert result.data['data']['count'] == len(expected)
    assert client.get(URL, {**params, 'owner': owner.pk + 1000}).data['data']['count'] == 0


@pytest.mark.parametrize('params', [
    {'created_from': '2026-02-30'}, {'created_to': 'not-a-date'},
    {'created_from': '20260801'}, {'created_to': '9999-12-31'},
    {'created_from': '2026-09-01', 'created_to': '2026-08-01'},
])
def test_bad_ranges_return_validation_error(dated_samples, params):
    client, _ = dated_samples
    assert client.get(URL, params).status_code == 400


def test_range_count_and_pagination_are_applied_in_database(dated_samples):
    client, _ = dated_samples
    params = {'created_from': '2026-08-01', 'created_to': '2026-08-31', 'page_size': 1, 'ordering': 'created_at'}
    first = client.get(URL, params).data['data']
    second = client.get(URL, {**params, 'page': 2}).data['data']
    assert first['count'] == second['count'] == 2
    assert first['results'][0]['fulfillment_no'] == 'DATE-1'
    assert second['results'][0]['fulfillment_no'] == 'DATE-2'
