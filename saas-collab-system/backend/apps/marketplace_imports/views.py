from django.conf import settings
from rest_framework.decorators import api_view, permission_classes

from apps.common.exceptions import BusinessRuleViolation, get_scoped_object_or_404
from apps.common.query import pagination_query
from apps.common.responses import paginated_data, success_response
from apps.integrations.models import MarketplaceStoreMapping
from apps.permissions.api_permissions import (
    IsMarketplaceStoreRetryRunner,
    IsMarketplaceStoreSyncRunner,
    IsMarketplaceStoreViewer,
)
from apps.permissions.ui_p6_scopes import filter_store_mappings

from .models import MarketplaceImportBatch, MarketplaceInventorySnapshot, MarketplaceOrder
from .serializers import (
    ImportRequestSerializer,
    MarketplaceImportBatchSerializer,
    MarketplaceInventorySnapshotSerializer,
    MarketplaceOrderSerializer,
)
from .services import ImportRuleViolation, import_normalized_batch


SENSITIVE_INPUT_KEYS = {
    "access_token",
    "accesstoken",
    "token",
    "refreshtoken",
    "refresh_token",
    "authorization_code",
    "authorizationcode",
    "app_secret",
    "appsecret",
    "api_secret",
    "apisecret",
    "api_key",
    "apikey",
    "client_secret",
    "clientsecret",
    "secret",
    "credentials",
    "credential_ciphertext",
    "partner_key",
    "partnerkey",
    "cookie",
    "cookies",
    "session",
    "sessionid",
    "session_id",
    "bearer",
    "private_key",
    "privatekey",
}


def _reject_sensitive_input(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in SENSITIVE_INPUT_KEYS:
                raise ImportRuleViolation("Raw credentials are forbidden in the normalized import contract.")
            _reject_sensitive_input(child)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_input(child)


def _validated_payload(request):
    _reject_sensitive_input(request.data)
    serializer = ImportRequestSerializer(data=request.data)
    if not serializer.is_valid():
        raise BusinessRuleViolation(serializer.errors)
    return serializer.validated_data


def _scoped_store_mappings(request, permission_code):
    queryset = MarketplaceStoreMapping.objects.filter(
        tenant=request.user.tenant,
        status=MarketplaceStoreMapping.Status.ACTIVE,
    )
    return filter_store_mappings(request.user, queryset, permission_code)


def _store_mapping(request, store_mapping_id, permission_code):
    return get_scoped_object_or_404(
        _scoped_store_mappings(request, permission_code),
        pk=store_mapping_id,
    )


def _require_offline_import_enabled():
    if not settings.PR_A3_SYNTHETIC_IMPORT_ENABLED:
        raise ImportRuleViolation("Synthetic offline marketplace import is disabled.")


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreSyncRunner])
def import_collection(request):
    _require_offline_import_enabled()
    payload = _validated_payload(request)
    mapping = _store_mapping(request, payload["store_mapping_id"], "integrations.store.sync")
    batch, duplicate = import_normalized_batch(
        tenant=request.user.tenant,
        actor=request.user,
        store_mapping=mapping,
        payload=payload,
    )
    return success_response(
        {"duplicate": duplicate, "batch": MarketplaceImportBatchSerializer(batch).data},
        status=200 if duplicate else 201,
    )


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def batch_collection(request):
    mappings = _scoped_store_mappings(request, "integrations.store.view")
    queryset = MarketplaceImportBatch.objects.filter(
        tenant=request.user.tenant,
        store_mapping__in=mappings,
    ).select_related("store_mapping", "created_by")
    resource_type = request.query_params.get("resource_type")
    if resource_type:
        queryset = queryset.filter(resource_type=resource_type)
    page, page_size = pagination_query(request)
    return success_response(
        paginated_data(request, queryset, MarketplaceImportBatchSerializer, page=page, page_size=page_size)
    )


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreRetryRunner])
def retry_batch(request, pk):
    _require_offline_import_enabled()
    mappings = _scoped_store_mappings(request, "integrations.store.retry")
    batch = get_scoped_object_or_404(
        MarketplaceImportBatch.objects.filter(
            tenant=request.user.tenant,
            store_mapping__in=mappings,
            status=MarketplaceImportBatch.Status.FAILED,
        ),
        pk=pk,
    )
    payload = _validated_payload(request)
    if payload["store_mapping_id"] != batch.store_mapping_id or payload["resource_type"] != batch.resource_type:
        raise ImportRuleViolation("Retry payload does not match the failed batch boundary.")
    retried, duplicate = import_normalized_batch(
        tenant=request.user.tenant,
        actor=request.user,
        store_mapping=batch.store_mapping,
        payload=payload,
        allow_retry=True,
    )
    return success_response(
        {"duplicate": duplicate, "batch": MarketplaceImportBatchSerializer(retried).data}
    )


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def order_collection(request):
    mappings = _scoped_store_mappings(request, "integrations.store.view")
    queryset = MarketplaceOrder.objects.filter(
        tenant=request.user.tenant,
        store_mapping__in=mappings,
    ).prefetch_related("refunds")
    page, page_size = pagination_query(request)
    return success_response(
        paginated_data(request, queryset, MarketplaceOrderSerializer, page=page, page_size=page_size)
    )


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def inventory_collection(request):
    mappings = _scoped_store_mappings(request, "integrations.store.view")
    queryset = MarketplaceInventorySnapshot.objects.filter(
        tenant=request.user.tenant,
        store_mapping__in=mappings,
    ).select_related("product_mapping")
    page, page_size = pagination_query(request)
    return success_response(
        paginated_data(
            request,
            queryset,
            MarketplaceInventorySnapshotSerializer,
            page=page,
            page_size=page_size,
        )
    )
