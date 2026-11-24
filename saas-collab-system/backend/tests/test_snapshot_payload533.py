import pytest

from apps.supply_chain.snapshot_payload import pack_payload, unpack_payload


def test_large_evidence_round_trips_without_mutating_input():
    payload = {
        "source_run_ids": ["运行-编号-空值-" + str(i) for i in range(300)] + [None],
        "sales_archive_issues": {"金额": ["1234567890.012300", None] * 180},
        "other": None,
    }
    packed = pack_payload(payload)
    assert packed != payload
    assert packed["source_run_ids"].keys() == {"__zlib_json_v1__"}
    assert packed["sales_archive_issues"].keys() == {"__zlib_json_v1__"}
    assert unpack_payload(packed) == payload
    assert payload["source_run_ids"][-1] is None


def test_small_and_legacy_payloads_remain_readable():
    payload = {"source_run_ids": ["old-run"], "sales_archive_issues": None}
    assert pack_payload(payload) == payload
    assert unpack_payload(payload) is payload


def test_malformed_compressed_payload_is_rejected():
    payload = {"source_run_ids": {"__zlib_json_v1__": "not-base64!"}}
    with pytest.raises(ValueError):
        unpack_payload(payload)
