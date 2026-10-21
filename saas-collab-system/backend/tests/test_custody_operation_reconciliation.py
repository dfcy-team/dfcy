from apps.integrations.custody import FileCustodyBackend, CustodyError
from tests.test_custody_service import service, _request
import pytest


def test_closing_absent_operation_fences_late_storage(tmp_path):
    custody = FileCustodyBackend(tmp_path / "synthetic-records")
    assert custody.lookup_reference_by_operation("synthetic-operation", close=True) == {"found": False}
    with pytest.raises(CustodyError):
        custody.store_secrets(access_token="FAKE_ACCESS", operation_id="synthetic-operation")


def test_operation_lookup_returns_only_references_and_requires_service_auth(service):
    refs = _request(service, "/tokens", payload={"access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH",
        "operation_id": "synthetic-operation", "idempotency_key": "synthetic-operation"})["body"]
    assert _request(service, "/tokens/operation", token=None,
        payload={"operation_id": "synthetic-operation", "close": True})["status"] == 401
    result = _request(service, "/tokens/operation", payload={"operation_id": "synthetic-operation", "close": True})
    assert result["status"] == 200
    assert result["body"]["credential_id"] == refs["credential_id"]
    assert result["body"]["found"] is True
    assert "FAKE_ACCESS" not in str(result) and "FAKE_REFRESH" not in str(result)
    late = _request(service, "/tokens", payload={"access_token": "FAKE_LATE", "operation_id": "synthetic-operation"})
    assert late["status"] == 400
