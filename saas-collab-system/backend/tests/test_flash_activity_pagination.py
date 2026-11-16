from types import SimpleNamespace

import pytest

from apps.flash_sales.provider import Deferred, ShopeeAdapter


def reader(rows):
    adapter = ShopeeAdapter(SimpleNamespace())
    queries = []

    def call(endpoint, *, query):
        assert endpoint == "get_shop_flash_sale_list"
        assert 0 <= query["offset"] <= 1000
        assert 1 <= query["limit"] <= 100
        queries.append(dict(query))
        selected = [row for row in rows if row["type"] == query["type"]]
        if "start_time" in query:
            assert query["start_time"] < query["end_time"]
            selected = [row for row in selected
                        if query["start_time"] <= row["start_time"] <= query["end_time"]]
        offset = query["offset"]
        return {"flash_sale_list": selected[offset:offset + query["limit"]],
                "total_count": len(selected)}

    adapter.call = call
    return adapter, queries


def activity(number, *, start=None, kind=3):
    return {"flash_sale_id": number, "start_time": start if start is not None else 1700000000 + number * 3600,
            "type": kind}


def test_large_history_is_complete_without_exceeding_platform_offset():
    rows = [activity(i) for i in range(2558)] + [activity(3000, kind=1), activity(3001, kind=2)]
    adapter, queries = reader(rows)
    actual = adapter.activities()
    assert {row["flash_sale_id"] for row in actual} == {row["flash_sale_id"] for row in rows}
    assert len(actual) == len(rows)
    assert any("start_time" in query for query in queries)


def test_small_list_keeps_existing_unbounded_pagination():
    rows = [activity(i) for i in range(101)]
    adapter, queries = reader(rows)
    assert adapter.activities() == rows
    assert [query["offset"] for query in queries if query["type"] == 3] == [0, 100]
    assert all("start_time" not in query for query in queries)


def test_split_boundary_is_included_once():
    midpoint = 2145887999 // 2
    rows = [activity(i, start=midpoint - 1000 + i) for i in range(2001)]
    adapter, _ = reader(rows)
    actual = adapter.activities()
    assert len(actual) == len(rows)
    assert {row["flash_sale_id"] for row in actual} == set(range(2001))


def test_unsplittable_dense_second_never_returns_truncated_history():
    adapter, _ = reader([activity(i, start=1700000000) for i in range(1101)])
    with pytest.raises(Deferred, match="活动分页"):
        adapter.activities()


def test_window_coverage_must_match_unbounded_total():
    rows = [activity(i) for i in range(1101)] + [activity(2000, start=2145888000)]
    adapter, _ = reader(rows)
    with pytest.raises(Deferred, match="活动分页"):
        adapter.activities()


def test_duplicate_page_cannot_claim_complete_results():
    adapter, _ = reader([])
    adapter.call = lambda *args, **kwargs: {"flash_sale_list": [activity(1), activity(1)], "total_count": 2}
    with pytest.raises(Deferred, match="活动分页"):
        adapter.activities()


def test_changed_total_during_pagination_is_not_accepted():
    adapter, queries = reader([activity(i) for i in range(101)])
    original = adapter.call

    def changing(endpoint, *, query):
        data = original(endpoint, query=query)
        if query["offset"]:
            data["total_count"] += 1
        return data

    adapter.call = changing
    with pytest.raises(Deferred, match="活动分页"):
        adapter.activities()
    assert queries[-1]["offset"] == 100


def test_offset_limit_includes_last_allowed_page():
    rows = [activity(i) for i in range(1100)]
    adapter, queries = reader(rows)
    assert adapter.activities() == rows
    assert max(query["offset"] for query in queries) == 1000
    assert all("start_time" not in query for query in queries)


@pytest.mark.parametrize("include_list", [False, True])
def test_empty_time_windows_allow_missing_or_null_list(include_list):
    rows = [activity(i) for i in range(2558)]
    adapter, _ = reader(rows)
    original = adapter.call

    def empty_windows(endpoint, *, query):
        data = original(endpoint, query=query)
        if data["total_count"] == 0:
            if include_list:
                data["flash_sale_list"] = None
            else:
                del data["flash_sale_list"]
        return data

    adapter.call = empty_windows
    actual = adapter.activities()
    assert {row["flash_sale_id"] for row in actual} == set(range(2558))


@pytest.mark.parametrize("payload", [{"total_count": 1}, {"total_count": 1, "flash_sale_list": None}])
def test_nonempty_total_still_requires_list(payload):
    adapter, _ = reader([])
    adapter.call = lambda *args, **kwargs: payload
    with pytest.raises(Deferred, match="活动分页"):
        adapter.activities()
