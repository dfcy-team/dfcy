"""Small helpers shared by live OAuth providers.

``ProviderRequestId.mask`` turns any request identifier (URL, query string,
request id) into an opaque short mask. The raw value is never returned, logged
or persisted -- this keeps audit logs free of anything that could leak a token.
"""

import hashlib


class ProviderRequestId:
    @staticmethod
    def mask(value: str) -> str:
        if not value:
            return "req-****"
        digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
        return f"req-{digest[-6:]}"
