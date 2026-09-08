import hashlib
import ipaddress
import os
import re
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.query import pagination_query
from apps.common.error_codes import ErrorCode
from apps.common.responses import error_response, paginated_data, success_response
from apps.permissions.ui_p5_scopes import (
    filter_product_research,
    filter_product_skus,
    filter_product_spus,
    require_create_scope,
)
from apps.permissions.services import check_user_permission, get_permission_data_scopes

from .coding_services import SEASONS, category_path
from .category_metadata import category_metadata
from .standard_colors import STANDARD_COLORS
from .models import (
    ProductBundleComponent,
    ProductCategory,
    ProductColor,
    ProductAttribute,
    ProductLegacyItem,
    ProductResearch,
    ProductSKU,
    ProductSPU,
    ProductStatusRecommendation,
    ProductStatusTransition,
)
from apps.files.models import AttachmentFile
from .permissions import (
    IsProductAttributeReadOrManage,
    IsProductBundleReadOrManage,
    IsProductCategoryReadOrManage,
    IsProductCodeFreezer,
    IsProductColorReadOrManage,
    IsProductMasterReadOrManage,
    IsMasterdataSettingsReadOrManage,
    IsProductResearchReadOrManage,
    IsProductStatusConfirmer,
    IsProductStatusEvaluator,
    IsProductStatusViewer,
)
from .serializers import (
    ProductBundleComponentSerializer,
    ProductCategorySerializer,
    ProductCategoryBackgroundColorBulkSerializer,
    ProductColorSerializer,
    ProductAttributeSerializer,
    ProductLegacyItemSerializer,
    ProductDetailBulkUpdateSerializer,
    ProductSPUBulkUpdateSerializer,
    ProductResearchSerializer,
    ProductSKUSerializer,
    ProductSPUSerializer,
    ProductStatusRecommendationSerializer,
    ProductStatusTransitionSerializer,
)
from .status_services import confirm_recommendation, evaluate_mock_status, reject_recommendation


def _serializer_context(request):
    return {"request": request}


def _require_manage_scope(user, *permission_codes):
    """Require an all/own create scope for the permission that granted access.

    The product master workspace keeps backwards-compatible fallbacks (for
    example, ``products.master.manage`` can administer categories and colors).
    Checking only the most specific code after the request has already passed
    the fallback permission class incorrectly returns 403 to those managers.
    Keep the fallback explicit and still enforce the selected code's scope.
    """
    for permission_code in permission_codes:
        if check_user_permission(user, permission_code):
            require_create_scope(user, permission_code)
            return
    # Preserve the normal PermissionDenied response if the caller somehow
    # reaches this helper without one of the route's accepted permissions.
    require_create_scope(user, permission_codes[0])


def _require_category_manage_scope(user):
    return _require_manage_scope(user, "products.category.manage", "products.master.manage")


# Product images deliberately use a narrow, tenant-scoped storage boundary.
# This avoids placing binary data in ProductSKU and keeps URL uploads and file
# uploads on the same ``image_url`` business field.
PRODUCT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
PRODUCT_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
}
PRODUCT_IMAGE_MIME_TO_EXTENSION = {mime: extension for extension, mime in PRODUCT_IMAGE_TYPES.items()}
PRODUCT_IMAGE_REMOTE_TIMEOUT_SECONDS = 8
PRODUCT_IMAGE_MAX_REDIRECTS = 3
PRODUCT_IMAGE_CHUNK_BYTES = 64 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Expose redirects so every hop can be validated against SSRF rules."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _product_image_relative_path(tenant_id, extension):
    return f"product-images/tenant-{int(tenant_id)}/{secrets.token_hex(20)}{extension}"


def _validate_product_image(uploaded):
    if uploaded is None:
        raise ValueError("Image file is required.")
    if uploaded.size <= 0 or uploaded.size > PRODUCT_IMAGE_MAX_BYTES:
        raise ValueError("Image file must be between 1 byte and 5 MB.")
    original_name = str(getattr(uploaded, "name", "") or "")
    extension = Path(original_name).suffix.lower()
    expected_type = PRODUCT_IMAGE_TYPES.get(extension)
    content_type = str(getattr(uploaded, "content_type", "") or "").lower().split(";", 1)[0].strip()
    if not expected_type or content_type != expected_type:
        raise ValueError("Only jpg, jpeg, png, gif, webp and avif images with a matching MIME type are allowed.")
    head = uploaded.read(64)
    uploaded.seek(0)
    valid_magic = {
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".gif": head.startswith((b"GIF87a", b"GIF89a")),
        ".webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
        # AVIF is an ISO-BMFF file; require an avif/avis ftyp brand.
        ".avif": b"ftypavif" in head[4:32] or b"ftypavis" in head[4:32],
    }[extension]
    if not valid_magic:
        raise ValueError("The uploaded file content does not match its image type.")
    return extension, expected_type


def _stored_product_image_path(image_url):
    """Return a storage-relative path only for our own media URLs."""
    if not image_url:
        return None
    media_url = str(settings.MEDIA_URL or "/media/")
    if not media_url.startswith("/"):
        return None
    prefix = media_url.rstrip("/") + "/"
    if not str(image_url).startswith(prefix):
        return None
    relative = str(image_url)[len(prefix):].replace("\\", "/")
    if not relative.startswith("product-images/") or ".." in relative.split("/"):
        return None
    return relative


def _safe_local_product_image_path(image_url, tenant_id):
    """Validate a caller-supplied local media URL for this tenant only."""
    relative = _stored_product_image_path(image_url)
    tenant_prefix = f"product-images/tenant-{int(tenant_id)}/"
    if not relative or not relative.startswith(tenant_prefix):
        raise ValueError("本地图片地址必须属于当前租户。")
    if not default_storage.exists(relative):
        raise ValueError("本地图片文件不存在。")
    return relative


def _delete_product_image_if_unreferenced(image_url, *, exclude_sku_id=None, exclude_legacy_id=None):
    """Remove an internal image only after every product row releases it."""
    relative = _stored_product_image_path(image_url)
    if not relative:
        return False
    sku_refs = ProductSKU.objects.filter(image_url=image_url)
    legacy_refs = ProductLegacyItem.objects.filter(image_url=image_url)
    if exclude_sku_id is not None:
        sku_refs = sku_refs.exclude(pk=exclude_sku_id)
    if exclude_legacy_id is not None:
        legacy_refs = legacy_refs.exclude(pk=exclude_legacy_id)
    if sku_refs.exists() or legacy_refs.exists():
        return False
    default_storage.delete(relative)
    AttachmentFile.objects.filter(file_path=relative).delete()
    return True


def _reject_private_address(hostname, port):
    """Resolve a remote image host and fail closed for non-public addresses."""
    hostname = str(hostname or "").strip().rstrip(".").casefold()
    if not hostname or hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise ValueError("图片地址主机不允许使用本机或内网地址。")
    try:
        direct_ip = ipaddress.ip_address(hostname)
        addresses = [direct_ip]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise ValueError("图片地址主机无法解析。") from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
            except (IndexError, ValueError):
                continue
    if not addresses:
        raise ValueError("图片地址主机无法解析。")
    for address in addresses:
        if not address.is_global:
            raise ValueError("图片地址不允许访问内网、本机或保留地址。")


def _validate_remote_image_url(value):
    """Validate and normalize one external image URL before opening it."""
    value = str(value or "").strip()
    if len(value) > 2048:
        raise ValueError("图片地址不能超过 2048 个字符。")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("图片地址必须使用 http 或 https。")
    if parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("图片地址格式无效。")
    try:
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except ValueError as exc:
        raise ValueError("图片地址端口无效。") from exc
    # Restrict downloads to the conventional web ports.  This prevents the
    # importer from being used to probe arbitrary services on public hosts.
    if port not in {80, 443}:
        raise ValueError("图片地址只能使用 80 或 443 端口。")
    _reject_private_address(parsed.hostname, port)
    return value


def _image_magic_matches(content, extension):
    head = bytes(content[:64])
    return {
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".gif": head.startswith((b"GIF87a", b"GIF89a")),
        ".webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
        ".avif": b"ftypavif" in head[4:32] or b"ftypavis" in head[4:32],
    }.get(extension, False)


def _cached_remote_image_path(url, tenant_id):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]
    prefix = f"product-images/tenant-{int(tenant_id)}/remote-{digest}"
    for extension in PRODUCT_IMAGE_TYPES:
        candidate = f"{prefix}{extension}"
        if default_storage.exists(candidate):
            return candidate, PRODUCT_IMAGE_TYPES[extension], True
    return prefix, None, False


def _download_product_image(url, tenant_id):
    """Download one validated public image with bounded redirects and size."""
    normalized = _validate_remote_image_url(url)
    cached_path, cached_type, already_cached = _cached_remote_image_path(normalized, tenant_id)
    if already_cached:
        return cached_path, cached_type, True

    current_url = normalized
    response = None
    try:
        for redirect_count in range(PRODUCT_IMAGE_MAX_REDIRECTS + 1):
            # Validate every redirect target, including DNS answers, before the
            # next connection is opened.
            current_url = _validate_remote_image_url(current_url)
            request = urllib.request.Request(
                current_url,
                headers={
                    "Accept": ",".join(PRODUCT_IMAGE_TYPES.values()),
                    "User-Agent": "saas-collab-product-image-cache/1.0",
                },
                method="GET",
            )
            try:
                response = _NO_REDIRECT_OPENER.open(request, timeout=PRODUCT_IMAGE_REMOTE_TIMEOUT_SECONDS)
            except urllib.error.HTTPError as exc:
                response = exc
            status = int(response.getcode() or 0)
            if status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location") if response.headers else None
                response.close()
                response = None
                if not location or redirect_count >= PRODUCT_IMAGE_MAX_REDIRECTS:
                    raise ValueError("图片地址重定向次数过多或目标为空。")
                current_url = urllib.parse.urljoin(current_url, location)
                continue
            if status < 200 or status >= 300:
                raise ValueError(f"图片服务器返回 HTTP {status}。")
            break
        else:
            raise ValueError("图片地址重定向次数过多。")

        headers = getattr(response, "headers", None)
        content_type = ""
        if headers is not None:
            try:
                content_type = headers.get_content_type()
            except AttributeError:
                content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().casefold()
        content_type = str(content_type or "").split(";", 1)[0].strip().casefold()
        extension = PRODUCT_IMAGE_MIME_TO_EXTENSION.get(content_type)
        if not extension:
            raise ValueError("图片 Content-Type 必须是受支持的图片类型。")
        content_length = None
        try:
            content_length = int(headers.get("Content-Length")) if headers and headers.get("Content-Length") else None
        except (TypeError, ValueError):
            content_length = None
        if content_length is not None and (content_length <= 0 or content_length > PRODUCT_IMAGE_MAX_BYTES):
            raise ValueError("图片文件必须在 1 字节到 5 MB 之间。")

        buffer = bytearray()
        while True:
            chunk = response.read(PRODUCT_IMAGE_CHUNK_BYTES)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > PRODUCT_IMAGE_MAX_BYTES:
                raise ValueError("图片文件不能超过 5 MB。")
        content = bytes(buffer)
        if not content or not _image_magic_matches(content, extension):
            raise ValueError("图片文件头与 Content-Type 不匹配。")

        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:40]
        relative = f"product-images/tenant-{int(tenant_id)}/remote-{digest}{extension}"
        if default_storage.exists(relative):
            return relative, content_type, True
        saved_name = default_storage.save(relative, ContentFile(content))
        # FileSystemStorage can append a suffix during a race.  Prefer the
        # deterministic path and discard the duplicate if another request won.
        if saved_name != relative and default_storage.exists(relative):
            default_storage.delete(saved_name)
            saved_name = relative
        return saved_name, content_type, False
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ValueError("图片下载超时或网络不可用。") from exc
    finally:
        if response is not None:
            response.close()


def _replace_product_image(item, uploaded, request):
    extension, file_type = _validate_product_image(uploaded)
    relative = _product_image_relative_path(item.tenant_id, extension)
    media_root = Path(settings.MEDIA_ROOT).resolve()
    target = (media_root / relative).resolve()
    if media_root not in target.parents:
        raise ValueError("Invalid image storage path.")
    uploaded.seek(0)
    saved_name = default_storage.save(relative, ContentFile(uploaded.read()))
    media_url = f"{str(settings.MEDIA_URL).rstrip('/')}/{saved_name.replace(os.sep, '/') }"
    old_path = _stored_product_image_path(item.image_url)
    try:
        item.image_url = media_url
        item.save(update_fields=["image_url", "updated_at"])
        AttachmentFile.objects.create(
            tenant=item.tenant,
            file_name=str(getattr(uploaded, "name", "") or saved_name),
            file_path=saved_name,
            file_type=file_type,
            file_size=int(uploaded.size),
            uploaded_by=request.user,
            business_type="product_sku_image",
            business_id=str(item.pk),
            is_private=False,
        )
    except Exception:
        default_storage.delete(saved_name)
        raise
    if old_path and old_path != saved_name:
        old_media_url = f"{str(settings.MEDIA_URL).rstrip('/')}/{old_path}"
        _delete_product_image_if_unreferenced(old_media_url, exclude_sku_id=item.pk)
    return item


@api_view(["GET"])
@permission_classes([IsProductMasterReadOrManage])
def product_coding_options(request):
    return success_response({"seasons": SEASONS, "product_types": ProductSPU.ProductType.choices})


@api_view(["GET", "POST"])
@permission_classes([IsProductAttributeReadOrManage])
def product_attribute_collection(request):
    if request.method == "GET":
        queryset = ProductAttribute.objects.filter(tenant=request.user.tenant)
        return success_response(ProductAttributeSerializer(queryset, many=True).data)
    _require_manage_scope(
        request.user,
        "products.attribute.manage",
        "products.specification.manage",
        "products.master.manage",
    )
    with transaction.atomic():
        existing = list(ProductAttribute.objects.select_for_update().filter(tenant=request.user.tenant).values_list("code", flat=True))
        next_code = next((str(number) for number in range(1, 10) if str(number) not in existing), None)
        if next_code is None:
            return error_response(ErrorCode.STATE_CONFLICT, "一位属性编码已用完（1-9）。", status=409)
        serializer = ProductAttributeSerializer(data=request.data, context=_serializer_context(request))
        serializer.is_valid(raise_exception=True)
        item = serializer.save(tenant=request.user.tenant, code=next_code)
    return success_response(ProductAttributeSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductAttributeReadOrManage])
def product_attribute_detail(request, pk):
    item = get_object_or_404(ProductAttribute, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(ProductAttributeSerializer(item).data)
    if request.method == "DELETE":
        if ProductSPU.objects.filter(tenant=request.user.tenant, season_code=item.code).exists():
            return error_response(ErrorCode.STATE_CONFLICT, "属性存在关联数据，请停用。", status=409)
        item.delete()
        return success_response({"deleted": True})
    serializer = ProductAttributeSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductAttributeSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductCategoryReadOrManage])
def product_category_collection(request):
    if request.method == "GET":
        queryset = ProductCategory.objects.filter(tenant=request.user.tenant)
        level = request.query_params.get("level", "").strip()
        parent_id = request.query_params.get("parent_id", "").strip()
        if level.isdigit():
            queryset = queryset.filter(level=int(level))
        if parent_id.isdigit():
            queryset = queryset.filter(parent_id=int(parent_id))
        return success_response(ProductCategorySerializer(queryset, many=True).data)
    _require_category_manage_scope(request.user)
    serializer = ProductCategorySerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductCategorySerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductCategoryReadOrManage])
def product_category_detail(request, pk):
    item = get_object_or_404(ProductCategory, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        if item.children.exists():
            return error_response(ErrorCode.STATE_CONFLICT, "分类存在关联数据（含下级分类），请停用。", status=409)
        if item.products.exists():
            return error_response(ErrorCode.STATE_CONFLICT, "分类存在关联数据，请停用。", status=409)
        item.delete()
        return success_response({"deleted": True})
    if request.method == "GET":
        return success_response(ProductCategorySerializer(item).data)
    serializer = ProductCategorySerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            item = serializer.save()
    except DjangoValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "分类层级或编码无效。",
            data=getattr(exc, "message_dict", None) or {"detail": exc.messages},
            status=400,
        )
    except IntegrityError:
        return error_response(
            ErrorCode.STATE_CONFLICT,
            "目标上级下已存在相同分类编码。",
            status=409,
        )
    return success_response(ProductCategorySerializer(item).data)


@api_view(["GET", "PUT"])
@permission_classes([IsMasterdataSettingsReadOrManage])
def product_category_background_colors(request):
    queryset = ProductCategory.objects.filter(
        tenant=request.user.tenant,
        level=ProductCategory.Level.L2,
    ).order_by("code", "id")
    if request.method == "GET":
        return success_response(ProductCategorySerializer(queryset, many=True).data)

    serializer = ProductCategoryBackgroundColorBulkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    items = serializer.validated_data["items"]
    categories = {item.id: item for item in queryset.filter(id__in=[row["category_id"] for row in items])}
    if len(categories) != len(items):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "One or more L2 product categories do not belong to the current tenant.",
            status=400,
        )

    with transaction.atomic():
        for row in items:
            category = categories[row["category_id"]]
            category.row_background_color = row["row_background_color"].upper()
            category.save(update_fields=["row_background_color", "updated_at"])
    return success_response(ProductCategorySerializer(queryset, many=True).data)


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsProductAttributeReadOrManage])
def product_category_attributes(request, pk):
    item = get_object_or_404(ProductCategory, pk=pk, tenant=request.user.tenant)
    # A leaf L2 may own its specification dimensions until an L3 child is
    # introduced.  Automatic SPU/SKU coding still requires a complete L1/L2/L3
    # path and keeps using ``category_path`` for that stricter rule.
    supports_spec_dimensions = False
    if item.level == ProductCategory.Level.L3:
        try:
            category_path(item)
        except DjangoValidationError:
            pass
        else:
            supports_spec_dimensions = True
    elif item.level == ProductCategory.Level.L2:
        supports_spec_dimensions = bool(item.parent_id and not item.children.exists())
    if not supports_spec_dimensions:
        return error_response(ErrorCode.VALIDATION_ERROR, "规格只能设置在 L3 分类或没有 L3 下级的 L2 分类。", status=400)
    if request.method == "GET":
        return success_response({"category_id": item.id, "spec_dimensions": item.spec_dimensions})
    serializer = ProductCategorySerializer(
        item,
        data={"spec_dimensions": request.data.get("spec_dimensions", [])},
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response({"category_id": item.id, "spec_dimensions": item.spec_dimensions})


@api_view(["GET", "POST"])
@permission_classes([IsProductColorReadOrManage])
def product_color_collection(request):
    if request.method == "GET":
        queryset = ProductColor.objects.filter(tenant=request.user.tenant)
        return success_response(ProductColorSerializer(queryset, many=True).data)
    _require_manage_scope(request.user, "products.color.manage", "products.master.manage")
    serializer = ProductColorSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductColorSerializer(item).data, status=201)


@api_view(["POST"])
@permission_classes([IsProductColorReadOrManage])
def import_standard_product_colors(request):
    _require_manage_scope(request.user, "products.color.manage", "products.master.manage")
    created = updated = 0
    for code, name in STANDARD_COLORS:
        _, was_created = ProductColor.objects.update_or_create(
            tenant=request.user.tenant,
            code=code,
            defaults={"name": name, "is_active": True},
        )
        created += int(was_created)
        updated += int(not was_created)
    return success_response({"created": created, "updated": updated, "total": len(STANDARD_COLORS)}, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductColorReadOrManage])
def product_color_detail(request, pk):
    item = get_object_or_404(ProductColor, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        if ProductSKU.objects.filter(tenant=request.user.tenant, color_code=item.code).exists():
            return error_response(ErrorCode.STATE_CONFLICT, "颜色存在关联数据，请停用。", status=409)
        item.delete()
        return success_response({"deleted": True})
    if request.method == "GET":
        return success_response(ProductColorSerializer(item).data)
    serializer = ProductColorSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductColorSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductResearchReadOrManage])
def product_research_collection(request):
    if request.method == "GET":
        queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
        queryset = filter_product_research(request.user, queryset, "products.research.view")
        search = request.query_params.get("search", "").strip()
        platform = request.query_params.get("platform", "").strip()
        if search:
            queryset = queryset.filter(product_name__icontains=search)
        if platform:
            queryset = queryset.filter(platform=platform)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(request, queryset, ProductResearchSerializer, page=page, page_size=page_size)
        )

    require_create_scope(request.user, "products.research.manage", allow_own=True)
    serializer = ProductResearchSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ProductResearchSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductResearchReadOrManage])
def product_research_detail(request, pk):
    permission_code = "products.research.view" if request.method == "GET" else "products.research.manage"
    queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_research(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductResearchSerializer(item).data)

    serializer = ProductResearchSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductResearchSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_spu_collection(request):
    if request.method == "GET":
        queryset = ProductSPU.objects.filter(tenant=request.user.tenant).select_related(
            "category_node", "category_node__parent"
        ).prefetch_related("skus")
        queryset = filter_product_spus(request.user, queryset, "products.master.view")
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("sales_status", "").strip()
        if search:
            queryset = queryset.filter(product_name__icontains=search)
        if status:
            queryset = queryset.filter(sales_status=status)
        category_id = request.query_params.get("category_id", "").strip()
        if category_id.isdigit():
            selected = get_object_or_404(ProductCategory, pk=int(category_id), tenant=request.user.tenant)
            ids = [selected.id]
            frontier = [selected.id]
            while frontier:
                frontier = list(ProductCategory.objects.filter(tenant=request.user.tenant, parent_id__in=frontier).values_list("id", flat=True))
                ids.extend(frontier)
            queryset = queryset.filter(category_node_id__in=ids)
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSPUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSPUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSPUSerializer(item).data, status=201)


def _bulk_category_path(category):
    """Resolve the hierarchy accepted by safe bulk catalog edits.

    Automatic SPU/SKU coding still uses ``category_path`` and therefore
    requires an L3 leaf.  A bulk catalog move may intentionally target an
    active L2 node, especially for a not-yet-generated legacy item; return a
    ``None`` L3 marker for that case while retaining the tenant/parent checks.
    """
    if category.level == ProductCategory.Level.L2:
        if not category.parent_id or category.parent.level != ProductCategory.Level.L1:
            raise DjangoValidationError("L2 category must belong to an L1 category.")
        if category.parent.tenant_id != category.tenant_id:
            raise DjangoValidationError("Category hierarchy must stay within one tenant.")
        return category.parent, category, None
    return category_path(category)


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def product_spu_bulk_update(request):
    """Bulk-edit visible SPUs, including a safe catalog move.

    The endpoint intentionally excludes SPU codes and lifecycle/sales state;
    the latter remain controlled by their existing workflow endpoints.  A
    catalog move updates only category labels/codes and never rewrites SKU
    identifiers.
    """
    serializer = ProductSPUBulkUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    tenant = request.user.tenant
    ids = payload["ids"]
    fields = payload.get("fields") or {}

    queryset = filter_product_spus(
        request.user,
        ProductSPU.objects.filter(tenant=tenant).select_related("category_node", "category_node__parent", "category_node__parent__parent"),
        "products.master.manage",
    ).filter(pk__in=ids).order_by("id")
    visible = list(queryset)
    visible_by_id = {item.id: item for item in visible}
    targets = [visible_by_id[item_id] for item_id in ids if item_id in visible_by_id]
    result = {
        "matched": len(targets),
        "updated": 0,
        "unchanged": 0,
        "errors": [],
    }

    category = None
    if "category_node" in fields:
        try:
            category = ProductCategory.objects.select_related("parent", "parent__parent").get(
                pk=fields["category_node"], tenant=tenant, is_active=True,
            )
            if category.level not in {ProductCategory.Level.L2, ProductCategory.Level.L3}:
                raise ValueError
            # ``category_path`` is intentionally strict for automatic SKU
            # coding (which requires an L3 leaf).  Bulk catalog placement is
            # also used by the legacy-detail workflow, where an active L2 is
            # a valid owning category, so only require its parent hierarchy
            # here.
            _bulk_category_path(category)
        except (ProductCategory.DoesNotExist, DjangoValidationError, ValueError):
            return error_response(ErrorCode.VALIDATION_ERROR, "分类必须属于当前租户且为启用的二级或三级类目。", status=400)

    if payload.get("preview"):
        result["preview"] = True
        result["fields"] = sorted(fields)
        result["inaccessible_ids"] = [item_id for item_id in ids if item_id not in visible_by_id]
        return success_response(result)

    for item in targets:
        try:
            updates = []
            if "product_name" in fields and item.product_name != fields["product_name"]:
                item.product_name = fields["product_name"]
                updates.append("product_name")
            if "brand" in fields and item.brand != fields["brand"]:
                item.brand = fields["brand"]
                updates.append("brand")
            if category is not None and item.category_node_id != category.id:
                l1, l2, l3 = _bulk_category_path(category)
                item.category_node = category
                item.category = category.name
                item.l1_code = l1.code
                item.l2_code = l2.code
                item.l3_code = l3.code if l3 else ""
                updates.extend(["category_node", "category", "l1_code", "l2_code", "l3_code"])
            if updates:
                updates.append("updated_at")
                item.save(update_fields=list(dict.fromkeys(updates)))
                result["updated"] += 1
            else:
                result["unchanged"] += 1
        except Exception as exc:
            result["errors"].append({"id": item.id, "message": str(exc)})
    result["error_count"] = len(result["errors"])
    result["inaccessible_ids"] = [item_id for item_id in ids if item_id not in visible_by_id]
    return success_response(result)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_spu_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant).select_related(
        "category_node", "category_node__parent"
    ).prefetch_related("skus")
    item = get_object_or_404(filter_product_spus(request.user, queryset, permission_code), pk=pk)
    if request.method == "DELETE":
        # Re-read under a row lock.  The initial scoped lookup is for
        # authorization; the locked lookup makes the reference check and
        # deletion one transaction and avoids deleting after a concurrent
        # relation was created.
        with transaction.atomic():
            locked = get_object_or_404(
                filter_product_spus(
                    request.user,
                    ProductSPU.objects.filter(tenant=request.user.tenant),
                    "products.master.manage",
                ).select_for_update(),
                pk=pk,
            )
            references = _product_reverse_references(locked)
            if references:
                return error_response(
                    ErrorCode.STATE_CONFLICT,
                    "商品已被业务数据引用，不能删除，请改为停用。",
                    data={"can_deactivate": True, "references": references},
                    status=409,
                )
            spu_id = locked.pk
            before = {
                "spu_code": locked.spu_code,
                "product_name": locked.product_name,
                "lifecycle_status": locked.lifecycle_status,
                "sales_status": locked.sales_status,
            }
            try:
                locked.delete()
            except ProtectedError:
                # A relation may have been inserted between the generic
                # probes and the database delete.  Keep the contract a
                # deterministic 409 instead of leaking a 500.
                references = _product_reverse_references(locked)
                return error_response(
                    ErrorCode.STATE_CONFLICT,
                    "商品已被业务数据引用，不能删除，请改为停用。",
                    data={"can_deactivate": True, "references": references or ["protected_relation"]},
                    status=409,
                )
            from apps.audit.services import write_operation_log

            write_operation_log(
                tenant=request.user.tenant,
                user=request.user,
                module="products",
                action="product_spu.delete",
                object_type="ProductSPU",
                object_id=spu_id,
                before_data=before,
                after_data={"deleted": True},
            )
            return success_response({"deleted": True, "id": spu_id})
    if request.method == "GET":
        return success_response(ProductSPUSerializer(item).data)

    serializer = ProductSPUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductSPUSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsProductCodeFreezer])
def freeze_product_spu_code(request, pk):
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_spus(request.user, queryset, "products.master.freeze"), pk=pk)
    item.is_code_frozen = True
    item.skus.update(is_code_frozen=True)
    item.save(update_fields=["is_code_frozen", "updated_at"])
    return success_response(ProductSPUSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_collection(request):
    if request.method == "GET":
        queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related(
            "spu", "spu__category_node", "spu__category_node__parent"
        )
        queryset = filter_product_skus(request.user, queryset, "products.master.view")
        search = request.query_params.get("search", "").strip()
        spu_id = request.query_params.get("spu_id", "").strip()
        active_status = request.query_params.get("active_status", "active").strip()
        if search:
            queryset = queryset.filter(sku_code__icontains=search)
        if spu_id.isdigit():
            queryset = queryset.filter(spu_id=int(spu_id))
        if active_status == "active":
            queryset = queryset.filter(is_active=True)
        elif active_status == "inactive":
            queryset = queryset.filter(is_active=False)
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSKUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSKUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSKUSerializer(item).data, status=201)


def _sku_business_references(item):
    """Return every reverse relation that would make a SKU unsafe to delete.

    ProductSKU is consumed by several apps (orders, listings, inventory,
    alerts, bundles, imported legacy rows, and status/lifecycle evidence).
    Looking at ``_meta.related_objects`` keeps this check in sync when another
    app adds a real ForeignKey/OneToOne relation.  In particular, accessing a
    reverse one-to-one relation can raise ``DoesNotExist`` before a value is
    available, so the lookup must be inside the guarded block.
    """
    references = []
    for relation in item._meta.related_objects:
        accessor = relation.get_accessor_name()
        if not accessor:
            continue
        if relation.one_to_one:
            try:
                related = getattr(item, accessor)
            except relation.related_model.DoesNotExist:
                related = None
            exists = related is not None
        else:
            related = getattr(item, accessor, None)
            exists = bool(related is not None and related.exists())
        if exists:
            references.append(relation.related_model._meta.verbose_name)
    return sorted(set(references))


def _product_reverse_references(item):
    """Return all existing reverse FK/one-to-one references for a product.

    SPUs and SKUs share the same deletion rule.  The helper intentionally
    reports all reverse relations, including audit/status records and the
    legacy bridge, because deleting a referenced product must never silently
    leave an orphaned business or audit record.
    """
    return _sku_business_references(item)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related(
        "spu", "spu__category_node", "spu__category_node__parent"
    )
    item = get_object_or_404(filter_product_skus(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductSKUSerializer(item).data)
    if request.method == "DELETE":
        with transaction.atomic():
            # ``filter_product_skus`` uses ``distinct()`` for its custom
            # SPU-or-SKU predicate. PostgreSQL disallows ``FOR UPDATE`` on a
            # DISTINCT query, so resolve visibility in a subquery and lock
            # only the tenant-scoped SKU base row.
            visible_ids = filter_product_skus(
                request.user,
                ProductSKU.objects.filter(tenant=request.user.tenant),
                "products.master.manage",
            ).filter(pk=pk).values("pk")
            locked = get_object_or_404(
                ProductSKU.objects.filter(
                    tenant=request.user.tenant,
                    pk__in=visible_ids,
                ).select_for_update(of=("self",)),
                pk=pk,
            )
            references = _sku_business_references(locked)
            if references:
                return error_response(
                    ErrorCode.STATE_CONFLICT,
                    "该 SKU 已被业务数据引用，不能删除，请改为停用。",
                    data={"can_deactivate": True, "references": references},
                    status=409,
                )
            sku_id = locked.pk
            old_image_url = locked.image_url
            before = {
                "sku_code": locked.sku_code,
                "product_name": locked.product_name,
                "is_active": locked.is_active,
            }
            try:
                locked.delete()
            except ProtectedError:
                references = _sku_business_references(locked)
                return error_response(
                    ErrorCode.STATE_CONFLICT,
                    "该 SKU 已被业务数据引用，不能删除，请改为停用。",
                    data={"can_deactivate": True, "references": references or ["protected_relation"]},
                    status=409,
                )
            from apps.audit.services import write_operation_log

            write_operation_log(
                tenant=request.user.tenant,
                user=request.user,
                module="products",
                action="product_sku.delete",
                object_type="ProductSKU",
                object_id=sku_id,
                before_data=before,
                after_data={"deleted": True},
            )

            def cleanup_deleted_sku_media():
                # Storage cleanup must run only after the transaction commits.
                # If the audit write (or a later database operation) rolls the
                # deletion back, the still-live SKU must retain its image.
                _delete_product_image_if_unreferenced(old_image_url)
                AttachmentFile.objects.filter(
                    tenant=request.user.tenant,
                    business_type="product_sku_image",
                    business_id=str(sku_id),
                ).delete()

            transaction.on_commit(cleanup_deleted_sku_media)
            return success_response({"deleted": True, "id": sku_id})

    serializer = ProductSKUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    old_image_url = item.image_url
    item = serializer.save()
    # A URL edit replaces an uploaded image as well; remove the old binary
    # only when it belongs to this service's tenant-scoped storage boundary.
    old_image_path = _stored_product_image_path(old_image_url)
    new_image_path = _stored_product_image_path(item.image_url)
    if old_image_path and old_image_path != new_image_path:
        _delete_product_image_if_unreferenced(old_image_url, exclude_sku_id=item.pk)
    return success_response(ProductSKUSerializer(item).data)


@api_view(["POST", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_image(request, pk):
    """Upload or remove a SKU image while preserving tenant isolation."""
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(ProductSKU, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        old_image_url = item.image_url
        item.image_url = None
        item.save(update_fields=["image_url", "updated_at"])
        _delete_product_image_if_unreferenced(old_image_url, exclude_sku_id=item.pk)
        AttachmentFile.objects.filter(
            tenant=request.user.tenant,
            business_type="product_sku_image",
            business_id=str(item.pk),
        ).delete()
        return success_response(ProductSKUSerializer(item).data)
    uploaded = request.FILES.get("file") or request.FILES.get("image")
    try:
        item = _replace_product_image(item, uploaded, request)
    except ValueError as exc:
        return error_response(ErrorCode.VALIDATION_ERROR, str(exc), status=400)
    return success_response(ProductSKUSerializer(item).data)


def _prepare_legacy_dictionaries(item):
    standard_names = dict(STANDARD_COLORS)
    ProductColor.objects.update_or_create(
        tenant=item.tenant,
        code=item.color_code,
        defaults={
            "name": standard_names.get(item.color_code.lower(), item.color_code),
            "is_active": True,
        },
    )
    # The CSV importer reuses category instances while processing thousands of
    # rows. Reload before appending a specification so values added by earlier
    # rows are not overwritten by a stale in-memory spec_dimensions value.
    category = item.category_node
    category.refresh_from_db(fields=["spec_dimensions", "updated_at"])
    dimensions = list(category.spec_dimensions or [])
    dimensions_changed = False
    if not dimensions:
        dimensions = [{"code": "spec", "name": "规格", "values": []}]
        dimensions_changed = True
    first = dict(dimensions[0])
    values = list(first.get("values") or [])
    if item.specification and item.specification != "0" and item.specification not in values:
        values.append(item.specification)
        first["values"] = values
        dimensions[0] = first
        dimensions_changed = True
    if dimensions_changed:
        category.spec_dimensions = dimensions
        category.save(update_fields=["spec_dimensions", "updated_at"])


LEGACY_SKU_SYNC_FIELDS = (
    "product_name",
    "legacy_sku_code",
    "purchase_price",
    "unit",
    "image_url",
    "package_weight",
    "package_volume",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "origin_country",
    "hs_code",
    "product_description",
)


def _sync_legacy_fields_to_sku(item, sku=None):
    """Copy editable legacy-row fields onto its existing SKU in place.

    Generated rows are an audit bridge: editing an imported row must not
    allocate another SKU or change the generated identifier.  The SKU code is
    deliberately absent from ``LEGACY_SKU_SYNC_FIELDS`` and is therefore
    always preserved.  Variant dimensions (colour/specification/category)
    remain immutable after generation and are intentionally not copied.
    """

    sku = sku or item.generated_sku
    if sku is None:
        return None
    changed = []
    for field in LEGACY_SKU_SYNC_FIELDS:
        value = getattr(item, field)
        if getattr(sku, field) != value:
            setattr(sku, field, value)
            changed.append(field)
    if changed:
        changed.append("updated_at")
        sku.save(update_fields=changed)
    return sku


@transaction.atomic
def _generate_legacy_item(item, request):
    category = item.category_node
    # `_prepare_legacy_dictionaries` refreshes the relation while adding the
    # compatibility specification dimension.  Refresh here as well so this
    # helper remains correct when called directly or when Django returns a
    # separate relation instance from the request path.
    category.refresh_from_db(fields=["spec_dimensions", "updated_at"])
    # Legacy imports may stop at an active L2 category.  Treat its free-form
    # specification as a single ``spec`` dimension so the generated SKU still
    # has a stable, auditable code.  L3 categories retain their configured
    # dimensions and the normal coding rules.
    dimensions = category.spec_dimensions or [{"code": "spec"}]
    spec_values = {
        dimensions[0].get("code", "spec"): item.specification or "0"
    } if dimensions else {}
    # Re-generating an already generated import row is an in-place update.
    # This preserves the stable SKU identifier even when a user edits the
    # legacy code/name/details before pressing Generate again.
    existing_sku = None
    if item.generated_sku_id:
        existing_sku = (
            ProductSKU.objects.select_for_update()
            .select_related("spu")
            .filter(pk=item.generated_sku_id, tenant=request.user.tenant)
            .first()
        )
    if existing_sku is not None:
        spu = existing_sku.spu
        _sync_legacy_fields_to_sku(item, existing_sku)
        item.status = ProductLegacyItem.Status.GENERATED
        item.generated_spu = spu
        item.error_message = ""
        item.save(update_fields=["status", "generated_spu", "error_message", "updated_at"])
        return existing_sku

    spu = None
    if item.legacy_spu_code:
        spu = ProductSPU.objects.filter(
            tenant=request.user.tenant,
            legacy_spu_code=item.legacy_spu_code,
            category_node=category,
        ).first()
    if not spu:
        if category.level == ProductCategory.Level.L2:
            # Automatic SPU coding deliberately requires an L3 leaf.  Legacy
            # conversion is a compatibility path, so preserve L2 imports with
            # an explicit non-coded identifier instead of rejecting the row.
            parent = category.parent
            if parent is None or parent.tenant_id != request.user.tenant_id:
                raise DjangoValidationError("Legacy category hierarchy is invalid.")
            spu = ProductSPU.objects.create(
                tenant=request.user.tenant,
                spu_code=f"LEGACY-{item.id}",
                legacy_spu_code=item.legacy_spu_code,
                product_name=item.product_name,
                category=category.name,
                category_node=category,
                product_type=ProductSPU.ProductType.STANDARD,
                season_code=item.attribute_code or "0",
                l1_code=parent.code,
                l2_code=category.code,
                l3_code="",
            )
        else:
            spu_serializer = ProductSPUSerializer(
                data={
                    "product_name": item.product_name,
                    "category_node": category.id,
                    "season_code": item.attribute_code or "0",
                    "legacy_spu_code": item.legacy_spu_code,
                    "product_type": "standard",
                },
                context=_serializer_context(request),
            )
            spu_serializer.is_valid(raise_exception=True)
            spu = spu_serializer.save(tenant=request.user.tenant)
    sku_serializer = ProductSKUSerializer(
        data={
            "spu": spu.id,
            "product_name": item.product_name,
            "color_code": item.color_code,
            "spec_values": spec_values,
            "legacy_sku_code": item.legacy_sku_code,
            "purchase_price": item.purchase_price,
            "unit": item.unit,
            "image_url": item.image_url,
            "package_weight": item.package_weight,
            "package_volume": item.package_volume,
            "package_length_cm": item.package_length_cm,
            "package_width_cm": item.package_width_cm,
            "package_height_cm": item.package_height_cm,
            "origin_country": item.origin_country,
            "hs_code": item.hs_code,
            "product_description": item.product_description,
        },
        context=_serializer_context(request),
    )
    sku_serializer.is_valid(raise_exception=True)
    sku = sku_serializer.save(tenant=request.user.tenant)
    item.status = ProductLegacyItem.Status.GENERATED
    item.generated_spu = spu
    item.generated_sku = sku
    item.error_message = ""
    item.save(
        update_fields=["status", "generated_spu", "generated_sku", "error_message", "updated_at"]
    )
    return sku


def _detail_decimal(value):
    """Serialize nullable model decimals like the existing DRF fields.

    Keeping the model scale (rather than coercing to a binary JSON float) makes
    units/precision explicit to API consumers; null remains null for a missing
    source value.
    """
    return None if value is None else str(value)


def _product_detail_row_from_legacy(item):
    """Build the business-facing mapping row for an imported legacy SKU."""

    spu = getattr(item, "generated_spu", None)
    sku = getattr(item, "generated_sku", None)
    # Legacy bridge FKs are nullable and historical data may contain a bad
    # cross-tenant reference. Do not let a tenant-scoped detail response
    # expose any generated product data (especially its image) in that case.
    if spu is not None and spu.tenant_id != item.tenant_id:
        spu = None
    if sku is not None and sku.tenant_id != item.tenant_id:
        sku = None
    effective_category = getattr(item, "category_node", None)
    if effective_category is not None and effective_category.tenant_id != item.tenant_id:
        effective_category = None
    if effective_category is None and spu is not None:
        effective_category = getattr(spu, "category_node", None)
        if effective_category is not None and effective_category.tenant_id != item.tenant_id:
            effective_category = None
    category_info = category_metadata(effective_category, spu=spu)
    # Pending imports do not have a ProductSKU yet.  Their source name is still
    # the SKU-level name users need to review before generating a code.
    sku_name = sku.product_name if sku is not None and sku.product_name else item.product_name
    sku_active = sku.is_active if sku is not None else None
    # Generated rows are displayed through their current SKU identity.  The
    # cache endpoint updates both sides of a generated legacy mapping, but
    # older imports (and manually repaired records) may only have the image on
    # the legacy item.  Prefer the SKU image when it exists and retain the
    # legacy value as a compatibility fallback.
    image_url = (
        sku.image_url
        if sku is not None and sku.image_url
        else item.image_url
    )
    conversion_status = {
        ProductLegacyItem.Status.PENDING: "待调整",
        ProductLegacyItem.Status.GENERATED: "已生成",
        ProductLegacyItem.Status.ERROR: "生成失败",
    }.get(item.status, item.status)
    return {
        "id": item.id,
        "sku_id": sku.id if sku is not None else None,
        "row_type": "legacy",
        "legacy_spu_code": item.legacy_spu_code or "",
        "legacy_sku_code": item.legacy_sku_code,
        "spu_code": spu.spu_code if spu is not None else "",
        "sku_code": sku.sku_code if sku is not None else "",
        # Do not use the SPU name here.  The page is an SKU detail page.
        "sku_product_name": sku_name,
        "spu_product_name": spu.product_name if spu is not None else "",
        # Keep the old wire key for clients that still read it as an imported name.
        "product_name": item.product_name,
        "image_url": image_url,
        "category_node": item.category_node_id,
        "category_name": item.category_node.name if item.category_node_id else "",
        **category_info,
        "attribute_code": item.attribute_code or "0",
        "color_code": item.color_code or (sku.color_code if sku is not None else ""),
        "specification": item.specification or (sku.specification if sku is not None else ""),
        "purchase_price": _detail_decimal(
            item.purchase_price if item.purchase_price is not None else (sku.purchase_price if sku is not None else None)
        ),
        # Physical/customs data belongs to the imported legacy row.  Do not
        # fall back to generated SKU values here: the detail bridge must keep
        # the source record auditable even if the generated SKU is edited.
        "package_weight": _detail_decimal(item.package_weight),
        "package_volume": _detail_decimal(item.package_volume),
        "package_length_cm": _detail_decimal(item.package_length_cm),
        "package_width_cm": _detail_decimal(item.package_width_cm),
        "package_height_cm": _detail_decimal(item.package_height_cm),
        "origin_country": item.origin_country,
        "hs_code": item.hs_code,
        "conversion_status": item.status,
        "conversion_status_name": conversion_status,
        "status": item.status,
        "status_name": conversion_status,
        "sku_is_active": sku_active,
        "sku_status": "active" if sku_active is True else "inactive" if sku_active is False else "ungenerated",
        "sku_status_name": "在售" if sku_active is True else "下架" if sku_active is False else "未生成",
        "error_message": item.error_message or "",
        "updated_at": item.updated_at,
    }


def _product_detail_row_from_sku(sku):
    spu = sku.spu
    category_info = category_metadata(getattr(spu, "category_node", None), spu=spu)
    return {
        "id": sku.id,
        "sku_id": sku.id,
        "row_type": "sku",
        "legacy_spu_code": spu.legacy_spu_code or "",
        "legacy_sku_code": sku.legacy_sku_code or "",
        "spu_code": spu.spu_code,
        "sku_code": sku.sku_code,
        "sku_product_name": sku.product_name or "",
        "spu_product_name": spu.product_name,
        "product_name": sku.product_name or "",
        "image_url": sku.image_url or None,
        "category_node": spu.category_node_id,
        "category_name": spu.category or (spu.category_node.name if spu.category_node_id else ""),
        **category_info,
        "attribute_code": spu.season_code or "0",
        "color_code": sku.color_code or "",
        "specification": sku.specification or "",
        "purchase_price": _detail_decimal(sku.purchase_price),
        "package_weight": _detail_decimal(sku.package_weight),
        "package_volume": _detail_decimal(sku.package_volume),
        "package_length_cm": _detail_decimal(sku.package_length_cm),
        "package_width_cm": _detail_decimal(sku.package_width_cm),
        "package_height_cm": _detail_decimal(sku.package_height_cm),
        "origin_country": sku.origin_country,
        "hs_code": sku.hs_code,
        "conversion_status": "sku",
        "conversion_status_name": "已生成",
        "status": "sku",
        "status_name": "在售" if sku.is_active else "下架",
        "sku_is_active": sku.is_active,
        "sku_status": "active" if sku.is_active else "inactive",
        "sku_status_name": "在售" if sku.is_active else "下架",
        "error_message": "",
        "updated_at": sku.updated_at,
    }


def _filter_product_legacy_items(user, queryset, permission_code):
    """Apply the same tenant/data-scope contract as SKU rows.

    A custom SKU/SPU scope can only expose generated legacy bridge rows that
    point at an allowed SKU/SPU.  Pending imports have no generated identity
    and therefore remain visible only to an all-scope role, which is also the
    scope required for writes/imports.
    """

    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope.get("scope_type") == "all" for scope in scopes):
        return queryset.filter(tenant=user.tenant)
    allowed_skus = filter_product_skus(
        user,
        ProductSKU.objects.filter(tenant=user.tenant),
        permission_code,
    )
    allowed_ids = set()
    for scope in scopes:
        config = scope.get("config") or {}
        values = config.get("legacy_item_ids", [])
        if isinstance(values, list):
            allowed_ids.update(int(value) for value in values if str(value).isdigit())
    return queryset.filter(
        Q(generated_sku_id__in=allowed_skus.values("id"))
        | Q(generated_spu_id__in=allowed_skus.values("spu_id"))
        | Q(pk__in=allowed_ids)
    ).distinct()


def _attach_cached_product_image(item, relative_path, file_type, request, *, business_type):
    """Point one SKU/legacy row at a cached image and audit the attachment."""
    if item.tenant_id != request.user.tenant_id:
        raise ValueError("图片目标不属于当前租户，拒绝跨租户写入。")
    media_url = f"{str(settings.MEDIA_URL).rstrip('/')}/{relative_path.replace(os.sep, '/') }"
    if item.image_url == media_url:
        return False, media_url
    old_image_url = item.image_url
    item.image_url = media_url
    item.save(update_fields=["image_url", "updated_at"])
    AttachmentFile.objects.create(
        tenant=item.tenant,
        file_name=Path(relative_path).name,
        file_path=relative_path,
        file_type=file_type or "application/octet-stream",
        file_size=int(default_storage.size(relative_path) or 0),
        uploaded_by=request.user,
        business_type=business_type,
        business_id=str(item.pk),
        is_private=False,
    )
    _delete_product_image_if_unreferenced(
        old_image_url,
        exclude_sku_id=item.pk if isinstance(item, ProductSKU) else None,
        exclude_legacy_id=item.pk if isinstance(item, ProductLegacyItem) else None,
    )
    return True, media_url


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_detail_bulk_cache_images(request):
    """Cache image URLs for old SKU rows and/or generated SKU rows.

    Each input row is independent so one bad URL cannot discard successful
    rows.  The target lookup is tenant/data-scope filtered, and a generated
    legacy row updates both sides of its old/new mapping.
    """
    raw_items = request.data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return error_response(ErrorCode.VALIDATION_ERROR, "items 必须是至少包含一行的数组。", status=400)
    # Remote image retrieval is intentionally bounded to keep the synchronous
    # request inside the reverse-proxy timeout.  Clients should submit larger
    # imports in batches of at most 20 rows and merge the per-row results.
    if len(raw_items) > 20:
        return error_response(ErrorCode.VALIDATION_ERROR, "单次最多处理 20 行图片，请分批提交。", status=400)

    tenant = request.user.tenant
    legacy_queryset = _filter_product_legacy_items(
        request.user,
        ProductLegacyItem.objects.filter(tenant=tenant).select_related("generated_sku", "generated_spu"),
        "products.master.manage",
    )
    sku_queryset = filter_product_skus(
        request.user,
        ProductSKU.objects.filter(tenant=tenant, spu__tenant=tenant).select_related("spu"),
        "products.master.manage",
    )
    result = {"processed": len(raw_items), "cached": 0, "reused": 0, "updated": 0, "unchanged": 0, "error_count": 0, "errors": [], "results": []}

    for index, raw in enumerate(raw_items):
        row_result = {"index": index}
        try:
            if not isinstance(raw, dict):
                raise ValueError("每行必须是对象。")
            legacy_code = str(raw.get("legacy_sku_code") or raw.get("old_sku_code") or "").strip()
            sku_code = str(raw.get("sku_code") or raw.get("new_sku_code") or "").strip()
            image_url = str(raw.get("image_url") or raw.get("url") or "").strip()
            if not legacy_code and not sku_code:
                raise ValueError("legacy_sku_code 和 sku_code 至少填写一项。")
            if not image_url:
                raise ValueError("image_url 不能为空。")
            if len(legacy_code) > 160 or len(sku_code) > 80:
                raise ValueError("SKU 编码长度超出限制。")

            legacy = legacy_queryset.filter(legacy_sku_code=legacy_code).first() if legacy_code else None
            sku = sku_queryset.filter(sku_code=sku_code).first() if sku_code else None
            if legacy is None and legacy_code:
                raise ValueError("旧 SKU 不存在或不在当前数据范围内。")
            if sku is None and sku_code:
                raise ValueError("新 SKU 不存在或不在当前数据范围内。")
            if legacy is None and sku is None:
                raise ValueError("旧 SKU 或新 SKU 不存在或不在当前数据范围内。")
            if legacy is not None and legacy.generated_sku_id:
                generated_sku = legacy.generated_sku
                if generated_sku is None or generated_sku.tenant_id != tenant.id:
                    raise ValueError("旧 SKU 的生成关系不属于当前租户，拒绝跨租户写入。")
            if legacy is not None and sku is not None:
                if legacy.generated_sku_id != sku.id:
                    raise ValueError("旧 SKU 与新 SKU 不属于同一条商品映射关系。")

            targets = []
            if legacy is not None:
                targets.append((legacy, "product_legacy_item_image"))
                if legacy.generated_sku_id and legacy.generated_sku is not None:
                    targets.append((legacy.generated_sku, "product_sku_image"))
            elif sku is not None:
                targets.append((sku, "product_sku_image"))
            # The direct sku identifier can be supplied with a generated legacy
            # row; the identity check above ensures it is the same target.
            if sku is not None and all(item.pk != sku.pk for item, _ in targets):
                targets.append((sku, "product_sku_image"))

            relative = None
            file_type = None
            was_cached = False
            if image_url.startswith("/media/"):
                relative = _safe_local_product_image_path(image_url, tenant.id)
                extension = Path(relative).suffix.lower()
                file_type = PRODUCT_IMAGE_TYPES.get(extension)
                if not file_type:
                    raise ValueError("本地图片类型不受支持。")
                was_cached = True
            else:
                relative, file_type, was_cached = _download_product_image(image_url, tenant.id)

            changed = False
            media_url = f"{str(settings.MEDIA_URL).rstrip('/')}/{relative.replace(os.sep, '/') }"
            with transaction.atomic():
                for target, business_type in targets:
                    updated, media_url = _attach_cached_product_image(
                        target,
                        relative,
                        file_type,
                        request,
                        business_type=business_type,
                    )
                    changed = changed or updated
            if was_cached:
                result["reused"] += 1
            else:
                result["cached"] += 1
            if changed:
                result["updated"] += 1
                row_result["status"] = "updated"
            else:
                result["unchanged"] += 1
                row_result["status"] = "unchanged"
            row_result["image_url"] = media_url
            if legacy_code:
                row_result["legacy_sku_code"] = legacy_code
            if sku_code:
                row_result["sku_code"] = sku_code
        except Exception as exc:
            result["error_count"] += 1
            row_result["status"] = "error"
            row_result["message"] = str(exc)
            if isinstance(raw, dict):
                for key in ("legacy_sku_code", "sku_code"):
                    if raw.get(key):
                        row_result[key] = str(raw[key]).strip()
            result["errors"].append(row_result.copy())
        result["results"].append(row_result)
    return success_response(result)


@api_view(["GET"])
@permission_classes([IsProductMasterReadOrManage])
def product_detail_collection(request):
    """Return one paginated, tenant-scoped view of legacy mappings and SKUs.

    Imported rows remain visible after generation so users can audit the old/new
    relationship.  Standalone SKUs are included once, while a SKU already linked
    to a legacy row is represented by that mapping row instead of being duplicated.
    """

    tenant = request.user.tenant
    legacy_queryset = _filter_product_legacy_items(
        request.user,
        ProductLegacyItem.objects.filter(tenant=tenant),
        "products.master.view",
    ).select_related(
        "category_node", "category_node__parent",
        "generated_spu", "generated_spu__category_node", "generated_spu__category_node__parent",
        "generated_sku", "generated_sku__spu", "generated_sku__spu__category_node",
        "generated_sku__spu__category_node__parent",
    )
    sku_queryset = filter_product_skus(
        request.user,
        ProductSKU.objects.filter(tenant=tenant, spu__tenant=tenant).select_related(
            "spu", "spu__category_node", "spu__category_node__parent"
        ),
        "products.master.view",
    )

    search = request.query_params.get("search", "").strip()
    if search:
        search_filter = (
            Q(legacy_spu_code__icontains=search)
            | Q(legacy_sku_code__icontains=search)
            | Q(product_name__icontains=search)
            | Q(generated_spu__spu_code__icontains=search)
            | Q(generated_spu__product_name__icontains=search)
            | Q(generated_sku__sku_code__icontains=search)
            | Q(generated_sku__product_name__icontains=search)
            | Q(category_node__name__icontains=search)
            | Q(generated_spu__category_node__name__icontains=search)
            | Q(color_code__icontains=search)
            | Q(specification__icontains=search)
            | Q(purchase_price__icontains=search)
            | Q(package_weight__icontains=search)
            | Q(package_volume__icontains=search)
            | Q(origin_country__icontains=search)
            | Q(hs_code__icontains=search)
        )
        legacy_queryset = legacy_queryset.filter(search_filter)
        sku_queryset = sku_queryset.filter(
            Q(sku_code__icontains=search)
            | Q(legacy_sku_code__icontains=search)
            | Q(product_name__icontains=search)
            | Q(spu__spu_code__icontains=search)
            | Q(spu__product_name__icontains=search)
            | Q(spu__category_node__name__icontains=search)
            | Q(color_code__icontains=search)
            | Q(specification__icontains=search)
            | Q(purchase_price__icontains=search)
            | Q(package_weight__icontains=search)
            | Q(package_volume__icontains=search)
            | Q(origin_country__icontains=search)
            | Q(hs_code__icontains=search)
        )

    category_id = request.query_params.get("category_id", "").strip()
    if category_id.isdigit():
        selected = get_object_or_404(ProductCategory, pk=int(category_id), tenant=tenant)
        category_ids = [selected.id]
        frontier = [selected.id]
        while frontier:
            frontier = list(ProductCategory.objects.filter(tenant=tenant, parent_id__in=frontier).values_list("id", flat=True))
            category_ids.extend(frontier)
        legacy_queryset = legacy_queryset.filter(
            Q(category_node_id__in=category_ids) | Q(generated_spu__category_node_id__in=category_ids)
        )
        sku_queryset = sku_queryset.filter(spu__category_node_id__in=category_ids)

    sku_status = request.query_params.get("sku_status", request.query_params.get("active_status", "all")).strip()
    if sku_status == "active":
        legacy_queryset = legacy_queryset.filter(generated_sku__is_active=True)
        sku_queryset = sku_queryset.filter(is_active=True)
    elif sku_status == "inactive":
        legacy_queryset = legacy_queryset.filter(generated_sku__is_active=False)
        sku_queryset = sku_queryset.filter(is_active=False)

    page, page_size = pagination_query(request)
    # Keep linked SKUs out of the standalone stream without materializing all
    # legacy rows or serializing the entire tenant before slicing the page.
    # The subquery also preserves the legacy/SKU visibility and filters.
    linked_sku_ids = legacy_queryset.exclude(generated_sku_id=None).values("generated_sku_id")
    standalone_skus = sku_queryset.exclude(pk__in=linked_sku_ids).order_by("sku_code")
    legacy_ordered = legacy_queryset.order_by("-created_at", "id")
    legacy_count = legacy_ordered.count()
    standalone_count = standalone_skus.count()
    total_count = legacy_count + standalone_count

    # ``Paginator.get_page`` clamps out-of-range pages to the last page (and
    # uses page 1 for an empty result). Preserve that public API contract while
    # slicing the database querysets directly.
    last_page = max(1, (total_count + page_size - 1) // page_size)
    page = min(page, last_page)
    offset = (page - 1) * page_size
    end = offset + page_size
    rows = []
    if offset < legacy_count:
        legacy_page = legacy_ordered[offset:min(end, legacy_count)]
        rows.extend(_product_detail_row_from_legacy(item) for item in legacy_page)
        remaining = page_size - len(rows)
        if remaining > 0:
            rows.extend(_product_detail_row_from_sku(item) for item in standalone_skus[:remaining])
    else:
        sku_offset = offset - legacy_count
        rows.extend(
            _product_detail_row_from_sku(item)
            for item in standalone_skus[sku_offset:sku_offset + page_size]
        )

    def page_url(target_page):
        if target_page is None:
            return None
        params = request.query_params.copy()
        params["page"] = target_page
        params["page_size"] = page_size
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return success_response(
        {
            "count": total_count,
            "next": page_url(page + 1) if page < last_page else None,
            "previous": page_url(page - 1) if page > 1 else None,
            "results": rows,
        }
    )


def _product_detail_bulk_ref(raw):
    """Return a stable (row type, id) selection key from UI payloads."""
    if isinstance(raw, dict):
        row_type = str(raw.get("row_type") or raw.get("type") or "").strip().lower()
        value = raw.get("id") or raw.get("pk")
    else:
        text = str(raw or "").strip()
        row_type, value = (text.split(":", 1) + [""])[:2] if ":" in text else ("", text)
    if row_type in {"legacy", "legacy_item", "old"}:
        row_type = "legacy"
    elif row_type in {"sku", "new"}:
        row_type = "sku"
    else:
        row_type = ""
    try:
        return row_type, int(value)
    except (TypeError, ValueError):
        return row_type, None


def _bulk_status_value(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "active", "on_sale", "on sale", "在售", "启用"}:
        return True
    if normalized in {"false", "0", "inactive", "off_sale", "off sale", "下架", "停用"}:
        return False
    raise ValueError("商品状态只能填写在售/下架（或启用/停用）。")


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def product_detail_bulk_update(request):
    """Bulk-edit safe SKU fields by an exact old/new SPU code.

    The bridge intentionally treats imported legacy rows and standalone SKU
    rows separately.  Generated codes and mapping foreign keys are never
    writable here; updates are tenant-scoped, row-locked and idempotent.
    """
    require_create_scope(request.user, "products.master.manage")
    serializer = ProductDetailBulkUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    tenant = request.user.tenant
    match_type = payload["match_type"]
    code = payload["spu_code"]
    fields = payload.get("fields") or {}
    refs = {_product_detail_bulk_ref(raw) for raw in (payload.get("ids") or [])}
    malformed = {ref for ref in refs if not ref[0] or ref[1] is None}
    if malformed:
        return error_response(ErrorCode.VALIDATION_ERROR, "Each selected row must include a valid id and row_type.", status=400)

    legacy_filter = {"tenant": tenant}
    sku_filter = {"tenant": tenant}
    if match_type == "old_spu":
        legacy_filter["legacy_spu_code"] = code
        sku_filter["spu__legacy_spu_code"] = code
    else:
        legacy_filter["generated_spu__spu_code"] = code
        sku_filter["spu__spu_code"] = code

    legacy_items = list(
        ProductLegacyItem.objects.select_for_update(of=("self",))
        .select_related("category_node", "generated_spu", "generated_sku")
        .filter(**legacy_filter)
        .order_by("id")
    )
    linked_sku_ids = {item.generated_sku_id for item in legacy_items if item.generated_sku_id}
    skus = list(
        ProductSKU.objects.select_for_update(of=("self",))
        .select_related("spu", "spu__category_node")
        .filter(**sku_filter)
        .exclude(pk__in=linked_sku_ids)
        .order_by("id")
    )
    if refs:
        legacy_items = [item for item in legacy_items if ("legacy", item.id) in refs or ("", item.id) in refs]
        skus = [sku for sku in skus if ("sku", sku.id) in refs or ("", sku.id) in refs]
    targets = [("legacy", item) for item in legacy_items] + [("sku", sku) for sku in skus]
    result = {"matched": len(targets), "updated": 0, "unchanged": 0, "errors": []}

    # Normalize field aliases once, retaining false/zero values.
    sentinel = object()
    name_value = fields.get("product_name", fields.get("sku_product_name"))
    price_value = fields.get("purchase_price", sentinel)
    status_value = fields.get("is_active", fields.get("sku_status", sentinel))
    category_value = fields.get("category_node", sentinel)
    clear_fields = set(payload.get("clear_fields") or [])
    # ``clear_fields`` was validated by the serializer; represent an explicit
    # clear as a real None value while ordinary empty values remain no-ops.
    for clear_field in clear_fields:
        if clear_field == "product_name":
            name_value = None
        elif clear_field == "purchase_price":
            price_value = None
    price = None
    if price_value is not sentinel and price_value is not None:
        try:
            price = Decimal(str(price_value))
            if price < 0:
                raise ValueError
        except (InvalidOperation, TypeError, ValueError):
            return error_response(ErrorCode.VALIDATION_ERROR, "采购价格必须是大于等于 0 的数字。", status=400)
    status = None
    if status_value is not sentinel:
        try:
            status = _bulk_status_value(status_value)
        except ValueError as exc:
            return error_response(ErrorCode.VALIDATION_ERROR, str(exc), status=400)
    category = None
    if category_value is not sentinel:
        try:
            category = ProductCategory.objects.get(pk=int(category_value), tenant=tenant)
            if not category.is_active:
                raise ValueError("Category must be active and belong to the current tenant.")
            # Keep bulk edits tenant-scoped and allow an active L2 owner for
            # legacy rows; automatic SKU coding remains L3-only elsewhere.
            _bulk_category_path(category)
        except (TypeError, ValueError, ProductCategory.DoesNotExist, DjangoValidationError):
            return error_response(ErrorCode.VALIDATION_ERROR, "分类必须属于当前租户且为有效分类。", status=400)

    if payload.get("preview"):
        result["preview"] = True
        return success_response(result)

    detail_fields = {
        "package_weight", "package_volume", "package_length_cm", "package_width_cm",
        "package_height_cm", "origin_country", "hs_code", "unit", "image_url", "product_description",
    }
    detail_values = {field: fields[field] for field in detail_fields if field in fields}
    detail_values.update({field: None for field in clear_fields if field in detail_fields})
    for row_type, item in targets:
        try:
            if (
                row_type == "legacy"
                and (
                    (
                        item.generated_spu_id
                        and (
                            item.generated_spu is None
                            or item.generated_spu.tenant_id != tenant.id
                        )
                    )
                    or (
                        item.generated_sku_id
                        and (
                            item.generated_sku is None
                            or item.generated_sku.tenant_id != tenant.id
                        )
                    )
                )
            ):
                raise ValueError("生成商品关系不属于当前租户，拒绝跨租户更新。")
            if category is not None and (row_type == "sku" or item.generated_sku_id):
                raise ValueError("已生成 SKU 的分类不可批量修改，以免破坏编码关系。")
            if status is not None and row_type == "legacy" and not item.generated_sku_id:
                raise ValueError("尚未生成 SKU 的记录不能修改商品状态。")
            changed = False
            if row_type == "legacy":
                legacy_updates = []
                if name_value is not None and item.product_name != name_value:
                    item.product_name = name_value; legacy_updates.append("product_name"); changed = True
                if price_value is not sentinel and item.purchase_price != price:
                    item.purchase_price = price; legacy_updates.append("purchase_price"); changed = True
                if category is not None and item.category_node_id != category.id:
                    item.category_node = category; legacy_updates.append("category_node"); changed = True
                legacy_detail_updates = []
                for field, value in detail_values.items():
                    if getattr(item, field) != value:
                        setattr(item, field, value)
                        legacy_detail_updates.append(field)
                        changed = True
                if changed:
                    item.save(update_fields=[*legacy_updates, *legacy_detail_updates, "updated_at"])
                if item.generated_sku_id:
                    sku = item.generated_sku
                    sku_changed = False
                    sku_updates = []
                    if name_value is not None and sku.product_name != name_value:
                        sku.product_name = name_value; sku_updates.append("product_name"); sku_changed = True
                    if price_value is not sentinel and sku.purchase_price != price:
                        sku.purchase_price = price; sku_updates.append("purchase_price"); sku_changed = True
                    if status is not None and sku.is_active != status:
                        sku.is_active = status; sku_updates.append("is_active"); sku_changed = True
                    sku_detail_updates = []
                    for field, value in detail_values.items():
                        if getattr(sku, field) != value:
                            setattr(sku, field, value)
                            sku_detail_updates.append(field)
                            sku_changed = True
                    if sku_changed:
                        sku.save(update_fields=[*sku_updates, *sku_detail_updates, "updated_at"])
                        changed = True
            else:
                sku = item
                updates = []
                if name_value is not None and sku.product_name != name_value:
                    sku.product_name = name_value; updates.append("product_name")
                if price_value is not sentinel and sku.purchase_price != price:
                    sku.purchase_price = price; updates.append("purchase_price")
                if status is not None and sku.is_active != status:
                    sku.is_active = status; updates.append("is_active")
                for field, value in detail_values.items():
                    if getattr(sku, field) != value:
                        setattr(sku, field, value)
                        updates.append(field)
                if updates:
                    updates.append("updated_at"); sku.save(update_fields=updates); changed = True
            result["updated" if changed else "unchanged"] += 1
        except Exception as exc:
            result["errors"].append({"id": item.id, "row_type": row_type, "message": str(exc)})
    result["error_count"] = len(result["errors"])
    return success_response(result)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_legacy_collection(request):
    if request.method == "GET":
        queryset = ProductLegacyItem.objects.filter(tenant=request.user.tenant).select_related(
            "category_node", "generated_spu", "generated_sku"
        )
        status_value = request.query_params.get("status", "").strip()
        if status_value:
            queryset = queryset.filter(status=status_value)
        return success_response(ProductLegacyItemSerializer(queryset, many=True).data)

    # Keep the HTTP boundary in this view, while the CSV parsing and row-level
    # transaction rules live in a dedicated service.  The import service is
    # imported lazily to avoid making the large legacy view module part of its
    # dependency graph.
    from .import_service import import_legacy_product_items

    require_create_scope(request.user, "products.master.manage")
    try:
        result, response_status = import_legacy_product_items(
            request=request,
            csv_text=request.data.get("csv_text"),
            mode=request.data.get("mode", "auto"),
        )
    except ValueError as exc:
        return error_response(ErrorCode.VALIDATION_ERROR, str(exc), status=400)
    return success_response(result, status=response_status)



@api_view(["PATCH", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def product_legacy_detail(request, pk):
    # Existing PATCH semantics intentionally remain restricted to all-tenant
    # create scope.  DELETE is a scoped resource action and relies on the
    # queryset below so a custom scope can delete only its configured rows.
    if request.method == "PATCH":
        require_create_scope(request.user, "products.master.manage")
    # Custom legacy visibility is expressed as an OR plus ``distinct()``
    # through the SKU/SPU scope helper. PostgreSQL disallows locking a
    # DISTINCT query, so resolve the scoped primary key first and then lock
    # only the tenant-scoped legacy base row.
    visible_ids = _filter_product_legacy_items(
        request.user,
        ProductLegacyItem.objects.filter(tenant=request.user.tenant),
        "products.master.manage",
    ).filter(pk=pk).values("pk")
    item = get_object_or_404(
        ProductLegacyItem.objects.filter(
            tenant=request.user.tenant,
            pk__in=visible_ids,
        ).select_for_update(of=("self",)),
        pk=pk,
    )
    if request.method == "DELETE":
        # A generated legacy row is the audit bridge for the generated SPU/SKU.
        # Removing only the source row would leave the generated SKU orphaned
        # from its import history, so it is a protected reference.  The UI can
        # still deactivate the generated SKU through its status action.
        references = _product_reverse_references(item)
        if item.generated_sku_id:
            references.append("generated_sku")
        if item.generated_spu_id:
            references.append("generated_spu")
        references = sorted(set(references))
        if references:
            return error_response(
                ErrorCode.STATE_CONFLICT,
                "已生成商品的明细属于商品映射记录，不能删除，请改为停用对应 SKU。",
                data={
                    # A legacy row with only a generated SPU is malformed and
                    # has no SKU status action to offer in the UI.
                    "can_deactivate": bool(item.generated_sku_id),
                    "references": references,
                    "sku_id": item.generated_sku_id,
                },
                status=409,
            )
        item_id = item.pk
        old_image_url = item.image_url
        before = {
            "legacy_sku_code": item.legacy_sku_code,
            "product_name": item.product_name,
            "status": item.status,
        }
        item.delete()
        from apps.audit.services import write_operation_log

        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="products",
            action="product_legacy_item.delete",
            object_type="ProductLegacyItem",
            object_id=item_id,
            before_data=before,
            after_data={"deleted": True},
        )

        def cleanup_deleted_legacy_media():
            # Defer physical storage cleanup until the delete and its audit
            # record are committed, preserving the file on rollback.
            _delete_product_image_if_unreferenced(old_image_url)
            AttachmentFile.objects.filter(
                tenant=request.user.tenant,
                business_type="product_legacy_item_image",
                business_id=str(item_id),
            ).delete()

        transaction.on_commit(cleanup_deleted_legacy_media)
        return success_response({"deleted": True, "id": item_id})
    was_generated = item.status == ProductLegacyItem.Status.GENERATED and bool(item.generated_sku_id)
    generated_sku = None
    if was_generated:
        generated_sku = (
            ProductSKU.objects.select_for_update()
            .filter(pk=item.generated_sku_id, tenant=request.user.tenant)
            .first()
        )
    serializer = ProductLegacyItemSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    if generated_sku is not None:
        # Keep the generated relation/status and update the existing SKU in
        # place.  In particular, no new SKU code is allocated for a simple
        # name, legacy-code, or detail edit.
        _sync_legacy_fields_to_sku(item, generated_sku)
        item.status = ProductLegacyItem.Status.GENERATED
        item.error_message = ""
        item.save(update_fields=["status", "error_message", "updated_at"])
    else:
        item.status = ProductLegacyItem.Status.PENDING
        item.error_message = ""
        item.save(update_fields=["status", "error_message", "updated_at"])
    return success_response(ProductLegacyItemSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_legacy_generate(request, pk):
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(ProductLegacyItem, pk=pk, tenant=request.user.tenant)
    category = item.category_node
    try:
        # Automatic coding requires an L3 leaf, but legacy data commonly has
        # only an active L2 owner.  The compatibility generator supports both
        # levels; `_generate_legacy_item` uses a deterministic LEGACY SPU code
        # for L2 rows while retaining normal L3 coding for new catalog data.
        valid_category = bool(
            category
            and category.tenant_id == request.user.tenant_id
            and category.is_active
            and category.level in {ProductCategory.Level.L2, ProductCategory.Level.L3}
            and _bulk_category_path(category)
        )
    except DjangoValidationError:
        valid_category = False
    if not valid_category:
        return error_response(ErrorCode.VALIDATION_ERROR, "请选择启用的二级或末级分类。", status=400)
    if not item.color_code:
        return error_response(ErrorCode.VALIDATION_ERROR, "请选择颜色。", status=400)
    try:
        _prepare_legacy_dictionaries(item)
        _generate_legacy_item(item, request)
    except Exception as exc:
        item.status = ProductLegacyItem.Status.ERROR; item.error_message = str(exc)[:500]
        item.save(update_fields=["status", "error_message", "updated_at"])
        return error_response(ErrorCode.VALIDATION_ERROR, item.error_message, status=400)
    return success_response(ProductLegacyItemSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductBundleReadOrManage])
def product_bundle_component_collection(request):
    queryset = ProductBundleComponent.objects.filter(tenant=request.user.tenant).select_related(
        "bundle_sku__spu", "component_sku__spu"
    )
    bundle_sku_id = request.query_params.get("bundle_sku_id", "").strip()
    if bundle_sku_id.isdigit():
        queryset = queryset.filter(bundle_sku_id=int(bundle_sku_id))
    if request.method == "GET":
        visible_skus = filter_product_skus(
            request.user,
            ProductSKU.objects.filter(tenant=request.user.tenant),
            "products.bundle.view",
        )
        queryset = queryset.filter(bundle_sku_id__in=visible_skus.values("id"))
        return success_response(ProductBundleComponentSerializer(queryset, many=True).data)
    _require_manage_scope(request.user, "products.bundle.manage", "products.master.manage")
    serializer = ProductBundleComponentSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductBundleComponentSerializer(item).data, status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsProductBundleReadOrManage])
def product_bundle_component_detail(request, pk):
    item = get_object_or_404(ProductBundleComponent, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        item.delete()
        return success_response({"deleted": True})
    serializer = ProductBundleComponentSerializer(
        item, data=request.data, partial=True, context=_serializer_context(request)
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductBundleComponentSerializer(item).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_recommendation_collection(request):
    queryset = ProductStatusRecommendation.objects.filter(tenant=request.user.tenant).select_related(
        "spu",
        "sku",
        "source_snapshot",
        "confirmed_by",
    )
    return success_response(ProductStatusRecommendationSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_recommendation_detail(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    return success_response(ProductStatusRecommendationSerializer(recommendation).data)


@api_view(["POST"])
@permission_classes([IsProductStatusConfirmer])
def confirm_status_recommendation(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    transition = confirm_recommendation(recommendation, request.user, reason=request.data.get("reason", ""))
    return success_response(ProductStatusTransitionSerializer(transition).data)


@api_view(["POST"])
@permission_classes([IsProductStatusConfirmer])
def reject_status_recommendation(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    reject_recommendation(recommendation, request.user, reason=request.data.get("reason", ""))
    recommendation.refresh_from_db()
    return success_response(ProductStatusRecommendationSerializer(recommendation).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_transition_collection(request):
    queryset = ProductStatusTransition.objects.filter(tenant=request.user.tenant).select_related(
        "spu",
        "sku",
        "recommendation",
        "approved_by",
    )
    return success_response(ProductStatusTransitionSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsProductStatusEvaluator])
def evaluate_mock_status_view(request):
    spu_id = request.data.get("spu")
    sku_id = request.data.get("sku")
    recommendation = evaluate_mock_status(
        tenant=request.user.tenant,
        user=request.user,
        spu_id=spu_id,
        sku_id=sku_id,
        metrics=request.data.get("metrics") or {},
    )
    return success_response(ProductStatusRecommendationSerializer(recommendation).data, status=201)
