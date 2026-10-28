"""Report-only key contract over the existing private OSS transport.

Reuse credentials/TLS/immutable PUT primitives already in V306, not the frozen
V313 paired RAW backup or its retention policy. No public or presigned URL.
"""
import re
from apps.integrations.raw_oss_storage import PrivateRawOSSStorage


class PrivateReportOSSStorage(PrivateRawOSSStorage):
    def _validate_key(self, name):
        pattern = rf"reports/{re.escape(self.namespace)}/tenant-[1-9][0-9]*/[0-9a-f]{{32}}\.(?:csv|txt)"
        if not isinstance(name, str) or not re.fullmatch(pattern, name):
            raise ValueError("Invalid report object key.")
        return name
