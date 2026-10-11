from itertools import combinations

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.shopee_advertising import DEFAULT_DATASETS
from tests.test_shopee_advertising import (
    SCOPE, campaign_page, client, performance_page, response, settings_page,
)


@pytest.mark.parametrize("datasets", [list(items) for size in range(1, 5)
                                      for items in combinations(DEFAULT_DATASETS, size)])
def test_calls_only_selected_datasets_and_required_campaign_ids(datasets):
    instance = client()
    expected = set()
    replies = {
        "get_product_level_campaign_id_list": campaign_page(),
        "get_product_level_campaign_setting_info": settings_page(),
        "get_product_campaign_daily_performance": performance_page(),
        "get_all_cpc_ads_daily_performance": response([{"date": "01-10-2026", "expense": 2}]),
        "get_total_balance": response({"data_timestamp": 1790812800, "total_balance": 3}),
    }
    if set(datasets) & {"campaign", "campaign_daily"}:
        expected.add("get_product_level_campaign_id_list")
    for kind, endpoint in zip(DEFAULT_DATASETS, list(replies)[1:]):
        if kind in datasets:
            expected.add(endpoint)

    def selected_only(path, query):
        endpoint = path.rsplit("/", 1)[-1]
        assert endpoint in expected, f"Unselected API called: {endpoint}"
        return replies[endpoint]

    instance._request.side_effect = selected_only
    cursor = None
    records = []
    for _ in range(5):
        page = instance.fetch_advertising(cursor, {**SCOPE, "advertising_datasets": datasets})
        records.extend(page["records"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert not cursor
    assert {row["kind"] for row in records} == set(datasets)
    calls = [call.args[0].rsplit("/", 1)[-1] for call in instance._request.call_args_list]
    assert set(calls) == expected
    assert len(calls) == len(expected)


def test_resume_rejects_phase_not_in_selected_datasets_without_request():
    instance = client()
    with pytest.raises(ValidationError):
        instance.fetch_advertising('{"phase":"campaigns"}', {**SCOPE, "advertising_datasets": ["balance"]})
    instance._request.assert_not_called()
