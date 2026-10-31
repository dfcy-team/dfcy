import socket
from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.influencers.models import TikTokVideoDailyMetric
from apps.integrations.gmv_max_sync import summarize


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network access is disabled in this test")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _page(number, total, rows):
    return {"page_info": {"page": number, "page_size": 100,
            "total_page": (total + 99) // 100, "total_number": total}, "list": rows}


def _campaign(campaign_id, *, cost="1", revenue="2", orders="1"):
    return {"dimensions": {"campaign_id": str(campaign_id)},
            "metrics": {"cost": cost, "gross_revenue": revenue, "orders": orders}}


def test_gmv_max_summarize_requires_and_summarizes_complete_pagination():
    pages = [_page(1, 101, [_campaign(i) for i in range(100)]),
             _page(2, 101, [_campaign(100)])]
    assert summarize(pages) == {"campaign_count": 101, "cost": "101",
                                "gross_revenue": "202", "orders": 101}
    with pytest.raises(ValidationError):
        summarize([_page(1, 101, [_campaign(i) for i in range(100)])])


def test_gmv_max_summarize_rejects_duplicate_campaigns_and_negative_metrics():
    with pytest.raises(ValidationError):
        summarize([_page(1, 2, [_campaign("7"), _campaign("7")])])
    with pytest.raises(ValidationError):
        summarize([_page(1, 1, [_campaign("7", cost="-0.01")])])


def test_video_native_ctr_ctor_fields_allow_null_and_values_over_one():
    ctr = TikTokVideoDailyMetric._meta.get_field("ctr")
    ctor = TikTokVideoDailyMetric._meta.get_field("reported_ctor")
    assert ctr.null and ctor.null
    assert not any(getattr(v, "limit_value", None) == 1 for v in ctr.validators)
    assert not any(getattr(v, "limit_value", None) == 1 for v in ctor.validators)
    assert ctr.clean(Decimal("1.2345"), None) == Decimal("1.2345")
    assert ctor.clean(Decimal("1.2500"), None) == Decimal("1.2500")
    assert ctr.clean(None, None) is None
    assert ctor.clean(None, None) is None
