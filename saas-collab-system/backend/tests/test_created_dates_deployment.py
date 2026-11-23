from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError
from apps.influencers.date_filters import filter_created_dates


def test_inclusive_beijing_day():
    qs = Mock()
    assert filter_created_dates(qs, {'created_from': '2026-11-05', 'created_to': '2026-11-05'}) is qs.filter.return_value
    values = qs.filter.call_args.kwargs
    assert values['created_at__gte'].astimezone(timezone.utc) == datetime(2026, 11, 4, 16, tzinfo=timezone.utc)
    assert values['created_at__lt'].astimezone(timezone.utc) == datetime(2026, 11, 5, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize('params,keys', [({}, set()), ({'created_from': '2026-11-05'}, {'created_at__gte'}), ({'created_to': '2026-11-05'}, {'created_at__lt'})])
def test_optional_bounds_preserve_scoped_queryset(params, keys):
    qs = Mock()
    filter_created_dates(qs, params)
    assert set(qs.filter.call_args.kwargs) == keys


@pytest.mark.parametrize('params', [
    {'created_from': '2026-11-06', 'created_to': '2026-11-05'},
    {'created_from': '2026-02-30'}, {'created_to': '9999-12-31'},
    {'created_from': '20261105'}, {'created_from': '2026-W01-1'},
])
def test_invalid_dates_rejected(params):
    qs = Mock()
    with pytest.raises(ValidationError):
        filter_created_dates(qs, params)
    qs.filter.assert_not_called()
