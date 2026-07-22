import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "fixtures"
MODULE_FILES = {
    "core": ("core.json",),
    "sales-inventory-finance-reconciliation": ("sales-inventory-finance-reconciliation.json",),
    "creator-management": ("creator-management.json",),
    "procurement": ("procurement.json",),
    "integration": (
        "core.json",
        "sales-inventory-finance-reconciliation.json",
        "creator-management.json",
        "procurement.json",
    ),
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"(?i)https?://(?!localhost|127\.0\.0\.1|example\.com)"),
    re.compile(r"(?i)\b(?:ghp_|sk-)[a-z0-9_-]{16,}"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
FORBIDDEN_KEYS = {"password", "token", "cookie", "session", "api_key", "api_secret", "private_key"}


def validate_response(route, response):
    if set(response) != {"success", "code", "message", "data"}:
        raise ValueError(f"{route}: response must contain only success/code/message/data")
    if response["success"] is not True or response["code"] != "OK":
        raise ValueError(f"{route}: fixture responses must be successful mock responses")
    data = response["data"]
    if isinstance(data, dict) and "results" in data:
        required = {"count", "next", "previous", "results"}
        if not required.issubset(data):
            raise ValueError(f"{route}: paginated response is incomplete")
        if data["count"] != len(data["results"]):
            raise ValueError(f"{route}: count does not match results")


def scan_value(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"{path}: forbidden credential key {key}")
            scan_value(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_value(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"{path}: forbidden real endpoint or credential-shaped value")


def validate_fixture(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError(f"{path.name}: schema_version must be 1")
    if document.get("status") != "mock":
        raise ValueError(f"{path.name}: status must remain mock")
    routes = document.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise ValueError(f"{path.name}: routes must be a non-empty object")
    for route, response in routes.items():
        if not route.startswith("/mock/") or not route.endswith("/"):
            raise ValueError(f"{path.name}: mock route must use /mock/*/ and a trailing slash")
        validate_response(route, response)
    scan_value(document)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", choices=tuple(MODULE_FILES), default="integration")
    args = parser.parse_args()
    for filename in MODULE_FILES[args.module]:
        validate_fixture(FIXTURE_DIR / filename)
    print(f"LOCAL_SANDBOX_FIXTURES=PASS module={args.module} files={len(MODULE_FILES[args.module])}")


if __name__ == "__main__":
    main()
