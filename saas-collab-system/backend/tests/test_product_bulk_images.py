from pathlib import Path

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.files.models import AttachmentFile
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def _user(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product image role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


class _Headers:
    def __init__(self, content_type="image/png", content_length=None, location=None):
        self.content_type = content_type
        self.content_length = content_length
        self.location = location

    def get_content_type(self):
        return self.content_type.split(";", 1)[0]

    def get(self, key, default=None):
        values = {
            "Content-Type": self.content_type,
            "Content-Length": str(self.content_length) if self.content_length is not None else None,
            "Location": self.location,
        }
        return values.get(key, default)


class _Response:
    def __init__(self, content, *, status=200, headers=None):
        self.content = content
        self.position = 0
        self.status = status
        self.headers = headers or _Headers(content_length=len(content))

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size < 0:
            size = len(self.content)
        result = self.content[self.position:self.position + size]
        self.position += len(result)
        return result

    def close(self):
        return None


@pytest.mark.django_db
def test_bulk_image_cache_updates_old_and_new_sku_and_is_idempotent(monkeypatch):
    tenant = Tenant.objects.create(name="Image tenant", code="image-tenant")
    user = _user(tenant, "image-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="IMG-SPU", product_name="SPU")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="IMG-SKU", product_name="SKU")
    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="IMG-OLD",
        product_name="Old SKU",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=sku,
    )
    content = b"\x89PNG\r\n\x1a\n" + b"test-image"
    opened = []
    monkeypatch.setattr(
        "apps.products.views.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "apps.products.views._NO_REDIRECT_OPENER.open",
        lambda request, timeout: (opened.append(request.full_url) or _Response(content)),
    )
    media_root = Path(__file__).resolve().parents[1] / ".test-product-image-cache"
    media_root.mkdir(parents=True, exist_ok=True)
    with override_settings(MEDIA_ROOT=media_root):
        client = APIClient()
        client.force_authenticate(user=user)
        payload = {
            "items": [{
                "legacy_sku_code": legacy.legacy_sku_code,
                "sku_code": sku.sku_code,
                "image_url": "https://cdn.example.test/products/img.png",
            }],
        }
        first = client.post("/api/internal/products/details/images/bulk-cache/", payload, format="json")
        assert first.status_code == 200
        assert first.json()["data"]["updated"] == 1
        assert first.json()["data"]["error_count"] == 0
        media_url = first.json()["data"]["results"][0]["image_url"]
        assert media_url.startswith("/media/product-images/tenant-")
        legacy.refresh_from_db()
        sku.refresh_from_db()
        assert legacy.image_url == media_url == sku.image_url
        assert AttachmentFile.objects.filter(tenant=tenant).count() == 2
        assert Path(media_root, media_url.removeprefix("/media/")).exists()

        opened.clear()
        second = client.post("/api/internal/products/details/images/bulk-cache/", payload, format="json")
        assert second.status_code == 200
        assert second.json()["data"]["unchanged"] == 1
        assert second.json()["data"]["reused"] == 1
        assert opened == []
        assert AttachmentFile.objects.filter(tenant=tenant).count() == 2

        old_path = Path(media_root, media_url.removeprefix("/media/"))
        new_content = b"\x89PNG\r\n\x1a\n" + b"replacement-image"
        monkeypatch.setattr(
            "apps.products.views._NO_REDIRECT_OPENER.open",
            lambda request, timeout: _Response(new_content),
        )
        replacement = client.post(
            "/api/internal/products/details/images/bulk-cache/",
            {"items": [{
                "legacy_sku_code": legacy.legacy_sku_code,
                "sku_code": sku.sku_code,
                "image_url": "https://cdn.example.test/products/replacement.png",
            }]},
            format="json",
        )
        assert replacement.status_code == 200
        assert replacement.json()["data"]["updated"] == 1
        replacement_url = replacement.json()["data"]["results"][0]["image_url"]
        assert not old_path.exists()
        assert Path(media_root, replacement_url.removeprefix("/media/")).exists()
        assert AttachmentFile.objects.filter(tenant=tenant).count() == 2


@pytest.mark.django_db
def test_bulk_image_cache_returns_partial_errors_and_rejects_private_hosts(monkeypatch):
    tenant = Tenant.objects.create(name="Image security tenant", code="image-security")
    user = _user(tenant, "image-security-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SEC-SPU", product_name="SPU")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SEC-SKU", product_name="SKU")
    monkeypatch.setattr(
        "apps.products.views.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    media_root = Path(__file__).resolve().parents[1] / ".test-product-image-cache-security"
    media_root.mkdir(parents=True, exist_ok=True)
    with override_settings(MEDIA_ROOT=media_root):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/internal/products/details/images/bulk-cache/",
            {"items": [
                {"sku_code": sku.sku_code, "image_url": "http://localhost/private.png"},
                {"sku_code": "MISSING-SKU", "image_url": "https://cdn.example.test/ok.png"},
            ]},
            format="json",
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["error_count"] == 2
        assert all(row["status"] == "error" for row in data["results"])
        sku.refresh_from_db()
        assert not sku.image_url


@pytest.mark.django_db
def test_bulk_image_cache_is_reflected_by_detail_rows_for_all_target_types(monkeypatch):
    """Cached images must be visible through the same detail API the UI reads.

    A generated legacy bridge can be targeted by its new SKU code.  In that
    case only the SKU side changes, so the row serializer must prefer the
    current SKU image over the stale imported image.  Pending legacy rows and
    standalone SKUs exercise the two other detail-row builders; a bad row is
    allowed to fail without hiding the successful rows.
    """
    tenant = Tenant.objects.create(name="Image detail tenant", code="image-detail")
    user = _user(tenant, "image-detail-user")
    generated_spu = ProductSPU.objects.create(tenant=tenant, spu_code="DETAIL-GEN-SPU", product_name="Generated")
    generated_sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=generated_spu,
        sku_code="DETAIL-GEN-SKU",
        product_name="Generated variant",
    )
    generated_legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="DETAIL-GEN-OLD",
        product_name="Imported generated variant",
        image_url="/media/product-images/tenant-legacy/stale.png",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=generated_spu,
        generated_sku=generated_sku,
    )
    pending = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="DETAIL-PENDING-OLD",
        product_name="Pending variant",
        status=ProductLegacyItem.Status.PENDING,
    )
    standalone_spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="DETAIL-STANDALONE-SPU",
        product_name="Standalone",
    )
    standalone = ProductSKU.objects.create(
        tenant=tenant,
        spu=standalone_spu,
        sku_code="DETAIL-STANDALONE-SKU",
        product_name="Standalone variant",
    )
    content = b"\x89PNG\r\n\x1a\n" + b"detail-image"
    monkeypatch.setattr(
        "apps.products.views.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "apps.products.views._NO_REDIRECT_OPENER.open",
        lambda request, timeout: _Response(content),
    )
    media_root = Path(__file__).resolve().parents[1] / ".test-product-image-cache-detail"
    media_root.mkdir(parents=True, exist_ok=True)
    with override_settings(MEDIA_ROOT=media_root):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/internal/products/details/images/bulk-cache/",
            {
                "items": [
                    # Target the new SKU only.  The linked legacy row should
                    # still display this current SKU image.
                    {"sku_code": generated_sku.sku_code, "image_url": "https://cdn.example.test/generated.png"},
                    {"legacy_sku_code": pending.legacy_sku_code, "image_url": "https://cdn.example.test/pending.png"},
                    {"sku_code": standalone.sku_code, "image_url": "https://cdn.example.test/standalone.png"},
                    {"sku_code": "DETAIL-MISSING-SKU", "image_url": "https://cdn.example.test/missing.png"},
                ],
            },
            format="json",
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["updated"] == 3
        assert payload["error_count"] == 1
        assert payload["results"][3]["index"] == 3
        assert payload["results"][3]["status"] == "error"

        generated_sku.refresh_from_db()
        generated_legacy.refresh_from_db()
        pending.refresh_from_db()
        standalone.refresh_from_db()
        assert generated_sku.image_url
        assert generated_legacy.image_url.endswith("stale.png")
        assert pending.image_url
        assert standalone.image_url

        detail = client.get("/api/internal/products/details/")
        assert detail.status_code == 200
        rows = detail.json()["data"]["results"]
        by_old = {row["legacy_sku_code"]: row for row in rows if row["legacy_sku_code"]}
        by_sku = {row["sku_code"]: row for row in rows if row["sku_code"]}

        # Generated bridge rows prefer the current SKU image even when the
        # imported legacy record still has its own old URL.
        assert by_old[generated_legacy.legacy_sku_code]["image_url"] == generated_sku.image_url
        assert by_old[pending.legacy_sku_code]["image_url"] == pending.image_url
        assert by_sku[standalone.sku_code]["image_url"] == standalone.image_url


@pytest.mark.django_db
def test_spu_bulk_update_moves_only_visible_tenant_records_and_rejects_state_fields():
    tenant = Tenant.objects.create(name="SPU bulk tenant", code="spu-bulk")
    other = Tenant.objects.create(name="Other SPU tenant", code="spu-bulk-other")
    user = _user(tenant, "spu-bulk-user")
    root = ProductCategory.objects.create(tenant=tenant, level=ProductCategory.Level.L1, code="1", name="Root")
    target = ProductCategory.objects.create(
        tenant=tenant, parent=root, level=ProductCategory.Level.L2, code="01", name="Target",
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="BULK-SPU", product_name="Old", brand="Old brand")
    hidden = ProductSPU.objects.create(tenant=other, spu_code="BULK-SPU", product_name="Other")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/internal/products/spus/bulk-update/",
        {"ids": [spu.id, hidden.id], "fields": {"brand": "New brand", "category_node": target.id}},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["data"]["matched"] == 1
    assert response.json()["data"]["updated"] == 1
    spu.refresh_from_db()
    assert spu.brand == "New brand"
    assert spu.category_node_id == target.id
    assert spu.category == "Target"
    assert (spu.l1_code, spu.l2_code, spu.l3_code) == ("1", "01", "")

    rejected = client.post(
        "/api/internal/products/spus/bulk-update/",
        {"ids": [spu.id], "fields": {"sales_status": "on_sale"}},
        format="json",
    )
    assert rejected.status_code == 400
