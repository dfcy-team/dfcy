"""Provider-neutral contract boundary for PR-A3.

Real Shopee/TikTok response adapters intentionally do not exist yet. The first
delivery accepts only the normalized synthetic contract so domain behavior can
be completed without guessing platform fields or calling a real API.
"""

from dataclasses import dataclass


NORMALIZED_CONTRACT_VERSION = "pr-a3-normalized-v1"
MAX_BATCH_RECORDS = 100
MAX_ORDER_LINES = 100
SUPPORTED_PLATFORMS = {"shopee", "tiktok"}


class PlatformResponseContractPending(RuntimeError):
    """Raised when code attempts to select an unavailable real adapter."""

    error_code = "PLATFORM_RESPONSE_CONTRACT_PENDING"


@dataclass(frozen=True)
class RetryBoundary:
    """Frozen retry boundary for future read-only provider adapters."""

    max_attempts: int = 3
    max_single_wait_seconds: int = 8
    max_total_wait_seconds: int = 15
    max_retry_after_seconds: int = 8
    retryable_statuses: tuple = (429, 500, 502, 503, 504)


def get_real_response_adapter(platform):
    normalized = str(platform or "").strip().lower()
    if normalized not in SUPPORTED_PLATFORMS:
        raise PlatformResponseContractPending("Unsupported marketplace platform.")
    raise PlatformResponseContractPending(
        f"{normalized} response mapping is pending approved API samples; real requests remain disabled."
    )
