from rest_framework.exceptions import ValidationError


class PlatformAdapter:
    adapter_name = "base"

    def fetch_page(self, sync_job, cursor_value=None):
        raise NotImplementedError

    def normalize_record(self, record):
        raise NotImplementedError

    def validate_record(self, record):
        raise NotImplementedError

    def persist_record(self, sync_job, record):
        raise NotImplementedError

    def get_next_cursor(self, page):
        raise NotImplementedError


class MockPlatformAdapter(PlatformAdapter):
    adapter_name = "mock"

    def fetch_page(self, sync_job, cursor_value=None):
        records = sync_job.integration_config.account_alias
        page_records = [
            {"external_id": f"{records}-001", "name": "demo item", "api_secret": "not-a-real-secret"},
            {"external_id": f"{records}-002", "name": "placeholder item", "token": "placeholder-token"},
        ]
        if cursor_value == "done":
            page_records = []
        return {"records": page_records, "next_cursor": "done"}

    def normalize_record(self, record):
        return {
            "external_id": record.get("external_id"),
            "name": record.get("name", ""),
        }

    def validate_record(self, record):
        return bool(record.get("external_id"))

    def persist_record(self, sync_job, record):
        return {"action": "skipped", "idempotency_key": f"{sync_job.id}:{record['external_id']}"}

    def get_next_cursor(self, page):
        return page.get("next_cursor", "")


class SandboxPlaceholderAdapter(MockPlatformAdapter):
    adapter_name = "sandbox-placeholder"


class DisabledProductionAdapter(PlatformAdapter):
    adapter_name = "disabled-production"

    def _reject(self):
        raise ValidationError("Production platform synchronization is disabled in phase 2.")

    def fetch_page(self, sync_job, cursor_value=None):
        self._reject()

    def normalize_record(self, record):
        self._reject()

    def validate_record(self, record):
        self._reject()

    def persist_record(self, sync_job, record):
        self._reject()

    def get_next_cursor(self, page):
        self._reject()


def get_adapter_for_config(config, force_mock=False):
    if force_mock or config.environment == "mock":
        return MockPlatformAdapter()
    if config.environment == "sandbox":
        return SandboxPlaceholderAdapter()
    return DisabledProductionAdapter()
