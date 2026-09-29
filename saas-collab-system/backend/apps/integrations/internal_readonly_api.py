"""Small, explicitly projected, tenant-scoped machine read API.

The configuration catalog is larger than this published contract. Never infer
an ORM model or fields from a caller-supplied resource name.
"""

import base64
import binascii
import ipaddress

from django.contrib.auth.hashers import check_password
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.responses import success_response
from apps.commerce.models import InventorySnapshot, RefundReturn, SalesOrder
from apps.development.models import DevelopmentProject
from apps.influencers.models import Influencer, OutreachTask, SampleFulfillment
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import CountrySiteMaster, PlatformMaster, StoreMaster, SupplierMaster, WarehouseMaster
from apps.products.models import ProductAttribute, ProductBundleComponent, ProductCategory, ProductColor, ProductResearch, ProductSKU, ProductSPU
from apps.purchasing.models import PurchaseOrder

from .models import InternalAPIClient, InternalAPIClientUsage, MarketplaceProductMapping
from .serializers import INTERNAL_API_RESOURCE_FIELDS


# Published fields, deliberately smaller than the configuration catalog's
# historical placeholder field lists. No credential, contact or cost columns.
READY = {
    "products": (ProductSPU, ("id", "spu_code", "product_name", "brand", "category", "lifecycle_status", "sales_status", "updated_at")),
    "product_details": (ProductSKU, ("id", "spu_id", "sku_code", "product_name", "color_code", "specification", "size", "material", "is_active", "updated_at")),
    "product_categories": (ProductCategory, ("id", "parent_id", "level", "code", "name", "english_name", "is_active", "updated_at")),
    "platforms": (PlatformMaster, ("id", "code", "name", "platform_type", "status", "updated_at")),
    "country_sites": (CountrySiteMaster, ("id", "code", "name", "country_code", "currency", "timezone", "status", "updated_at")),
    "suppliers": (SupplierMaster, ("id", "code", "name", "status", "updated_at")),
    "stores": (StoreMaster, ("id", "platform_id", "platform_site_id", "code", "name", "country_code", "currency", "status", "updated_at")),
    "warehouses": (WarehouseMaster, ("id", "code", "name", "country_code", "warehouse_type", "status", "updated_at")),
    "product_attributes": (ProductAttribute, ("id", "code", "name", "is_active", "updated_at")),
    "product_colors": (ProductColor, ("id", "code", "name", "is_active", "updated_at")),
    "product_mappings": (MarketplaceProductMapping, ("id", "platform", "store_mapping_id", "platform_product_id", "platform_variant_id", "platform_sku", "product_id", "sku_id", "status", "updated_at")),
    "product_bundles": (ProductBundleComponent, ("id", "bundle_sku_id", "component_sku_id", "quantity", "updated_at")),
    "platform_products": (PlatformProductDetail, ("id", "platform", "store_id", "site_id", "platform_product_id", "platform_variant_id", "platform_sku", "internal_sku_id", "title", "sales_status", "updated_at")),
    "product_research": (ProductResearch, ("id", "research_no", "product_name", "platform", "approval_status", "updated_at")),
    "development_projects": (DevelopmentProject, ("id", "project_no", "product_name", "stage", "status", "updated_at")),
    "purchase_orders": (PurchaseOrder, ("id", "po_no", "sku_code", "supplier_id", "quantity", "delivery_date", "status", "updated_at")),
    "sales_orders": (SalesOrder, ("id", "platform_id", "store_id", "external_order_id", "normalized_status", "business_date", "currency", "order_total_amount", "updated_at_utc")),
    "sales_returns": (RefundReturn, ("id", "platform_id", "store_id", "sales_order_id", "external_return_id", "normalized_status", "currency", "refund_amount", "updated_at")),
    "inventory_snapshots": (InventorySnapshot, ("id", "site_code", "warehouse_id", "internal_sku_id", "source_sku", "available_qty", "reserved_qty", "snapshot_at_utc")),
    "influencers": (Influencer, ("id", "code", "name", "platform", "handle", "cooperation_status", "status", "updated_at")),
    "outreach_tasks": (OutreachTask, ("id", "task_no", "task_name", "influencer_id", "store_id", "spu_id", "owner_id", "status", "updated_at")),
    "sample_fulfillments": (SampleFulfillment, ("id", "fulfillment_no", "outreach_task_id", "influencer_id", "store_id", "status", "shipped_at", "updated_at")),
}


def _denied(status=401):
    return Response({"detail": "Read access denied."}, status=status)


def _authenticate(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Basic ") or len(header) > 512:
        return None
    try:
        value = base64.b64decode(header[6:], validate=True).decode("utf-8")
        client_id, secret = value.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    if not client_id or not secret:
        return None
    client = InternalAPIClient.objects.filter(client_id=client_id).first()
    if not client or not check_password(secret, client.secret_hash):
        return None
    if client.status != InternalAPIClient.Status.ACTIVE or client.approval_status != InternalAPIClient.ApprovalStatus.APPROVED:
        return None
    if client.expires_at and client.expires_at <= timezone.now():
        return None
    try:
        source = _source_ip(request)
        if not any(source in ipaddress.ip_network(cidr, strict=True) for cidr in client.allowed_cidrs):
            return None
    except ValueError:
        return None
    return client


def _source_ip(request):
    """Use forwarded addresses only behind explicitly trusted direct peers."""
    peer = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    trusted = [ipaddress.ip_network(cidr, strict=True) for cidr in getattr(settings, "INTERNAL_READONLY_TRUSTED_PROXY_CIDRS", [])]
    if not any(peer in network for network in trusted):
        return peer
    header = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not header or len(header) > 1024:
        return peer
    chain = [ipaddress.ip_address(part.strip()) for part in header.split(",")]
    for candidate in reversed(chain):
        if not any(candidate in network for network in trusted):
            return candidate
    return chain[0]


def _consume_limit(client):
    minute = timezone.now().replace(second=0, microsecond=0)
    try:
        with transaction.atomic():
            row, _ = InternalAPIClientUsage.objects.select_for_update().get_or_create(
                client=client, window_start=minute, defaults={"request_count": 0},
            )
            updated = InternalAPIClientUsage.objects.filter(
                pk=row.pk, request_count__lt=client.rate_limit_per_minute,
            ).update(request_count=F("request_count") + 1)
            return bool(updated)
    except IntegrityError:
        # Concurrent first request: fail closed rather than accidentally bypass.
        return False


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def capabilities(request):
    return success_response({
        "ready_resources": [{"code": code, "fields": list(fields)} for code, (_, fields) in READY.items()],
        "pending_resources": sorted(set(INTERNAL_API_RESOURCE_FIELDS) - set(READY)),
    })


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def resource_collection(request, resource):
    client = _authenticate(request)
    if client is None:
        return _denied()
    if resource not in READY:
        return Response({"detail": "This data block is not online."}, status=404)
    if resource not in client.resources:
        return _denied(403)
    try:
        limit = int(request.query_params.get("limit", min(100, client.page_size_limit)))
        cursor = int(request.query_params.get("cursor", 0))
    except (TypeError, ValueError):
        return Response({"detail": "limit and cursor must be integers."}, status=400)
    if limit < 1 or limit > client.page_size_limit or cursor < 0:
        return Response({"detail": "Invalid pagination bounds."}, status=400)
    if not _consume_limit(client):
        return Response({"detail": "Rate limit exceeded."}, status=429)
    model, fields = READY[resource]
    rows = list(model.objects.filter(tenant_id=client.tenant_id, id__gt=cursor)
                .order_by("id").values(*fields)[:limit + 1])
    has_more = len(rows) > limit
    items = rows[:limit]
    return success_response({
        "resource": resource,
        "items": items,
        "next_cursor": items[-1]["id"] if has_more and items else None,
        "has_more": has_more,
    })
