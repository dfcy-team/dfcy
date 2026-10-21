import re
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[2]
VOUCHER_LOCATION = (
    r"^/api/internal/supply-chain/v2/costs/"
    r"(shipment|batch)/[0-9]+/settlements/[0-9]+/vouchers/$"
)
PROXY_SETTINGS = (
    "proxy_pass http://backend:8000;",
    "proxy_http_version 1.1;",
    "proxy_set_header Host $http_host;",
    "proxy_set_header X-Real-IP $remote_addr;",
    "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
    "proxy_set_header X-Forwarded-Proto https;",
)


def _location_block(source, location):
    match = re.search(rf"(?ms)^    location {re.escape(location)} \{{(.*?)^    \}}", source)
    assert match, f"missing nginx location {location}"
    return match.group(1)


def test_voucher_upload_has_scoped_proxy_limit_and_preserves_backend_cap():
    nginx = (SYSTEM_ROOT / "deploy/pilot/application/nginx.conf").read_text(encoding="utf-8")
    voucher = _location_block(nginx, f"~ {VOUCHER_LOCATION}")
    generic = _location_block(nginx, "/api/")

    assert "client_max_body_size 10m;" in nginx
    assert "client_max_body_size 12m;" in voucher
    assert "client_max_body_size" not in generic
    assert len(re.findall(r"client_max_body_size\s+12m;", nginx)) == 1
    assert all(setting in voucher for setting in PROXY_SETTINGS)
    assert all(setting in generic for setting in PROXY_SETTINGS)

    matcher = re.compile(VOUCHER_LOCATION)
    assert matcher.fullmatch("/api/internal/supply-chain/v2/costs/shipment/12/settlements/34/vouchers/")
    assert matcher.fullmatch("/api/internal/supply-chain/v2/costs/batch/12/settlements/34/vouchers/")
    assert not matcher.fullmatch("/api/internal/supply-chain/v2/costs/shipment/12/settlements/34/vouchers/1/download/")
    assert not matcher.fullmatch("/api/internal/supply-chain/v2/costs/shipment/12/settlements/34/records/")

    voucher_backend = (SYSTEM_ROOT / "backend/apps/supply_chain/payment_vouchers.py").read_text(encoding="utf-8")
    assert re.search(r"(?m)^MAX_BYTES\s*=\s*10\s*\*\s*1024\s*\*\s*1024\s*$", voucher_backend)
