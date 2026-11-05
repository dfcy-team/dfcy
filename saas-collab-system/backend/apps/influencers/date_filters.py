"""Inclusive Beijing calendar dates, without wrapping the indexed column."""
from datetime import date, datetime, time, timedelta, timezone

from rest_framework.exceptions import ValidationError


def filter_created_dates(queryset, params):
    try:
        def parse(value):
            if not value:
                return None
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError()
            return parsed

        start = parse(params.get('created_from', ''))
        end = parse(params.get('created_to', ''))
        if start and end and start > end:
            raise ValueError()
        zone = timezone(timedelta(hours=8))
        bounds = {}
        if start:
            bounds['created_at__gte'] = datetime.combine(start, time.min, zone)
        if end:
            bounds['created_at__lt'] = datetime.combine(end + timedelta(days=1), time.min, zone)
    except (ValueError, TypeError, OverflowError):
        raise ValidationError({'created_from': '请填写有效的创建日期范围，开始日期不能晚于结束日期。'})
    return queryset.filter(**bounds)
