from functools import reduce
from operator import or_

from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.accounts.miniapp_auth import MINIAPP_TOKEN_CHANNEL
from apps.accounts.models import CustomUser
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, ScopedResourceNotFound
from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.purchasing.models import SupplyPurchaseOrder

from .models import PackingBatchOrder, PackingSupplierCapability


CUSTOM_SCOPE_KEYS = {
    "supplier_ids",
    "packing_batch_ids",
    "supply_purchase_order_ids",
}


class IsNonMiniAppChannel(BasePermission):
    message = "A Mini Program token cannot access this API channel."

    def has_permission(self, request, view):
        token = request.auth
        return not (token and token.get("channel") == MINIAPP_TOKEN_CHANNEL)


def require_internal_permission(user, permission_code):
    if not (
        user
        and user.is_authenticated
        and user.is_active
        and user.user_type == CustomUser.UserType.INTERNAL
        and check_user_permission(user, permission_code)
    ):
        raise PermissionDenied("The requested packing permission is not available.")
    scopes = get_permission_data_scopes(user, permission_code)
    if not scopes:
        raise DataScopeDenied(
            "The declared packing permission has no data scope.",
            error_code=ErrorCode.DATA_SCOPE_MISSING,
        )
    return validate_scopes(scopes)


def _invalid_scope(message):
    raise DataScopeDenied(message, error_code=ErrorCode.DATA_SCOPE_INVALID)


def _positive_unique_ids(value, key):
    if not isinstance(value, list) or not 1 <= len(value) <= 500:
        _invalid_scope(f"Packing CUSTOM scope {key} must contain 1 to 500 IDs.")
    parsed = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            _invalid_scope(f"Packing CUSTOM scope {key} contains an invalid ID.")
        parsed.append(item)
    if len(parsed) != len(set(parsed)):
        _invalid_scope(f"Packing CUSTOM scope {key} contains duplicate IDs.")
    return frozenset(parsed)


def validate_scopes(scopes):
    validated = []
    for scope in scopes:
        scope_type = scope.get("scope_type")
        config = scope.get("config")
        if not isinstance(config, dict):
            _invalid_scope("Packing data-scope config must be a JSON object.")
        if scope_type == DataScope.ScopeType.DEPARTMENT:
            _invalid_scope("Department data scope is not supported for packing.")
        if scope_type in {DataScope.ScopeType.ALL, DataScope.ScopeType.OWN}:
            validated.append({"scope_type": scope_type, "config": {}})
            continue
        if scope_type != DataScope.ScopeType.CUSTOM:
            _invalid_scope("Packing data-scope type is invalid.")
        keys = set(config)
        if not keys or not keys <= CUSTOM_SCOPE_KEYS:
            _invalid_scope("Packing CUSTOM scope contains missing or unknown keys.")
        normalized = {key: _positive_unique_ids(config[key], key) for key in keys}
        validated.append({"scope_type": scope_type, "config": normalized})
    return validated


def filter_internal_batches(user, queryset, permission_code):
    scopes = require_internal_permission(user, permission_code)
    tenant_queryset = queryset.filter(tenant=user.tenant)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return tenant_queryset

    allowed_queries = []
    for index, scope in enumerate(scopes):
        scope_queryset = tenant_queryset
        if scope["scope_type"] == DataScope.ScopeType.OWN:
            scope_queryset = scope_queryset.filter(created_by=user)
        else:
            config = scope["config"]
            if "supplier_ids" in config:
                scope_queryset = scope_queryset.filter(supplier_id__in=config["supplier_ids"])
            if "packing_batch_ids" in config:
                scope_queryset = scope_queryset.filter(pk__in=config["packing_batch_ids"])
            if "supply_purchase_order_ids" in config:
                outside_orders = PackingBatchOrder.objects.filter(
                    batch_id=OuterRef("pk")
                ).exclude(order_id__in=config["supply_purchase_order_ids"])
                scope_queryset = scope_queryset.annotate(
                    **{f"_pack_scope_outside_{index}": Exists(outside_orders)}
                ).filter(**{f"_pack_scope_outside_{index}": False})
        allowed_queries.append(Q(pk__in=scope_queryset.values("pk")))

    if not allowed_queries:
        return tenant_queryset.none()
    return tenant_queryset.filter(reduce(or_, allowed_queries)).distinct()


def authorize_internal_create(user, supplier_id, order_ids):
    scopes = require_internal_permission(user, "supply.packing.create")
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return
    target_orders = frozenset(order_ids)
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        config = scope["config"]
        if (
            "supplier_ids" in config
            and "supply_purchase_order_ids" in config
            and supplier_id in config["supplier_ids"]
            and target_orders <= config["supply_purchase_order_ids"]
        ):
            return
    raise DataScopeDenied(
        "The requested supplier or purchase orders are outside the create scope.",
        error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
    )


def resolve_create_orders(user, order_ids):
    orders = list(
        SupplyPurchaseOrder.objects.filter(
            tenant=user.tenant,
            pk__in=order_ids,
        ).only("id", "supplier_id")
    )
    if len(orders) != len(set(order_ids)) or len({order.supplier_id for order in orders}) != 1:
        raise DataScopeDenied(
            "The requested purchase orders are outside the create scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    supplier_id = orders[0].supplier_id
    authorize_internal_create(user, supplier_id, order_ids)
    return supplier_id


def supplier_id_for_user(user):
    if not (
        user
        and user.is_authenticated
        and user.is_active
        and user.user_type == CustomUser.UserType.EXTERNAL
    ):
        raise PermissionDenied("An active external supplier account is required.")
    profile = getattr(user, "external_profile", None)
    if (
        not profile
        or profile.tenant_id != user.tenant_id
        or not profile.supplier_id
        or not SupplierMaster.objects.filter(
            tenant=user.tenant,
            pk=profile.supplier_id,
            status=StatusChoices.ACTIVE,
        ).exists()
    ):
        raise PermissionDenied("The supplier account is not bound to an active supplier.")
    return profile.supplier_id


def require_supplier_capability(user, supplier_id, *, mixed_orders=False):
    bound_supplier_id = supplier_id_for_user(user)
    if bound_supplier_id != supplier_id:
        raise ScopedResourceNotFound("Packing batch is not available for this supplier.")
    capability = PackingSupplierCapability.objects.filter(
        tenant=user.tenant,
        supplier_id=supplier_id,
    ).first()
    if not capability or not capability.can_self_pack:
        raise PermissionDenied("Supplier self-packing is not enabled.")
    if mixed_orders and not capability.can_mix_order_packing:
        raise PermissionDenied("Supplier mixed-order packing is not enabled.")
    return capability


def filter_supplier_batches(user, queryset):
    return queryset.filter(
        tenant=user.tenant,
        supplier_id=supplier_id_for_user(user),
    )
