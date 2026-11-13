import pytest
from apps.integrations.sync_services import _database_page_retry_allowed


def test_video_without_cached_page_does_not_refetch_day():
    assert not _database_page_retry_allowed('video_metrics', None, '', 0)
    assert not _database_page_retry_allowed('video_metrics', ('old', {}), 'current', 0)


def test_video_cached_database_page_can_retry_without_provider_call():
    assert _database_page_retry_allowed('video_metrics', ('current', {}), 'current', 0)
    assert not _database_page_retry_allowed('video_metrics', ('current', {}), 'current', 3)


@pytest.mark.parametrize('resource', ['affiliate_order', 'sales_order', 'advertising_report'])
def test_other_resource_retry_policy_is_preserved(resource):
    assert _database_page_retry_allowed(resource, None, '', 2)
    assert not _database_page_retry_allowed(resource, None, '', 3)
