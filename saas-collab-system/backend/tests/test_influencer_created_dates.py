from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from apps.influencers.date_filters import created_date_bounds
from apps.influencers.views import _filter_created_dates
from rest_framework.exceptions import ValidationError


def test_beijing_inclusive_range():
    bounds = created_date_bounds('2026-11-01', '2026-11-01')
    assert bounds['created_at__gte'].astimezone(timezone.utc) == datetime(2026, 10, 31, 16, tzinfo=timezone.utc)
    assert bounds['created_at__lt'].astimezone(timezone.utc) == datetime(2026, 11, 1, 16, tzinfo=timezone.utc)


def test_empty_and_open_ranges():
    assert created_date_bounds() == {}
    assert set(created_date_bounds('2026-11-01')) == {'created_at__gte'}
    assert set(created_date_bounds(end='2026-11-01')) == {'created_at__lt'}


@pytest.mark.parametrize('start,end', [
    ('2026-11-02', '2026-11-01'), ('2026-02-30', ''),
    ('20261101', ''), ('2026-W01-1', ''), ('', '9999-12-31'),
])
def test_invalid_range_is_api_validation_error(start, end):
    with pytest.raises(ValidationError):
        _filter_created_dates(Mock(), {'created_from': start, 'created_to': end})


def test_filter_preserves_existing_scoped_queryset():
    scoped = Mock()
    result = _filter_created_dates(scoped, {'created_from': '2026-11-01'})
    scoped.filter.assert_called_once_with(**created_date_bounds('2026-11-01'))
    assert result is scoped.filter.return_value
