from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError as APIValidationError
from rest_framework.response import Response
from rest_framework import serializers

from apps.masterdata.models import CountrySiteMaster, PlatformMaster, StatusChoices, WarehouseMaster, WAREHOUSE_TYPE_TO_PLATFORM_TYPE
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from apps.purchasing.supply_permissions import require_internal_supply_permission
from apps.tenants.models import Tenant
from .models import BusinessEvent, domain_write
from .permissions import MANAGE, VIEW
from .services import request_hash, _key


class WarehouseArchiveInput(serializers.Serializer):
    expected_version = serializers.IntegerField(required=False, min_value=1)
    code = serializers.SlugField(required=False, max_length=80)
    name = serializers.CharField(required=False, max_length=120, allow_blank=False, trim_whitespace=True)
    country_code = serializers.CharField(required=False, max_length=8, allow_blank=False, trim_whitespace=True)
    warehouse_type = serializers.ChoiceField(required=False, choices=WarehouseMaster.WarehouseType.choices)
    service_platform_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    status = serializers.ChoiceField(required=False, choices=StatusChoices.choices)
    address = serializers.CharField(required=False, max_length=500, allow_blank=True, trim_whitespace=True)
    region = serializers.CharField(required=False, max_length=80, allow_blank=True, trim_whitespace=True)
    legacy_codes = serializers.JSONField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate_legacy_codes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("飞书旧编码必须是字符串列表。")
        result, seen = [], set()
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 120:
                raise serializers.ValidationError("飞书旧编码每项须为 1 至 120 个字符的字符串。")
            item = item.strip()
            if item not in seen:
                result.append(item)
                seen.add(item)
            if len(result) > 20:
                raise serializers.ValidationError("最多维护 20 个飞书旧编码。")
        return result

    def validate(self, attrs):
        actor = self.context["actor"]
        instance = self.context.get("instance")
        if not instance:
            missing = {"code", "name", "country_code", "warehouse_type"} - set(attrs)
            if missing:
                raise serializers.ValidationError({key: "此字段必填。" for key in sorted(missing)})
        warehouse_type = attrs.get("warehouse_type", instance.warehouse_type if instance else None)
        country_code = attrs.get("country_code", instance.country_code if instance else None)
        platform_id = attrs.get("service_platform_id", instance.service_platform_id if instance else None)
        if not instance or "service_platform_id" in attrs:
            platform = PlatformMaster.objects.filter(pk=platform_id, tenant_id=actor.tenant_id, status=StatusChoices.ACTIVE).first() if platform_id else None
            if platform_id and not platform:
                raise serializers.ValidationError({"service_platform_id": "请选择当前租户已启用的仓储服务平台。"})
            expected = WAREHOUSE_TYPE_TO_PLATFORM_TYPE.get(warehouse_type)
            if platform and platform.platform_type != expected:
                raise serializers.ValidationError({"service_platform_id": "仓储服务平台类型必须与仓库类型一致。"})
            if not platform and warehouse_type != WarehouseMaster.WarehouseType.OWNED:
                raise serializers.ValidationError({"service_platform_id": "三方仓和平台仓必须绑定仓储服务平台。"})
            attrs["service_platform"] = platform
            attrs.pop("service_platform_id", None)
        if not instance and country_code and not CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, status=StatusChoices.ACTIVE, country_code__iexact=country_code).exists():
            raise serializers.ValidationError({"country_code": "请选择当前租户已启用的国家。"})
        if not warehouse_type or warehouse_type not in WAREHOUSE_TYPE_TO_PLATFORM_TYPE:
            raise serializers.ValidationError({"warehouse_type": "仓库类型无效。"})
        return attrs


def _scopes(actor, permission):
    if not actor.is_active or getattr(actor, "user_type", "internal") != "internal":
        raise PermissionDenied("需要有效的内部采购账号。")
    require_internal_supply_permission(actor, permission)
    scopes = get_permission_data_scopes(actor, permission, resource_code="masterdata.warehouses")
    if not scopes:
        raise PermissionDenied("仓库档案数据范围未配置。")
    return scopes


def warehouse_refs(actor, permission=VIEW):
    """Return tenant warehouses visible to supply workflows under warehouse resource scopes."""
    scopes = _scopes(actor, permission)
    query = WarehouseMaster.objects.filter(tenant_id=actor.tenant_id)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return query
    ids = set()
    unrestricted_reference = False
    for scope in scopes:
        kind = scope["scope_type"]
        config = scope.get("config") or {}
        if kind == DataScope.ScopeType.OWN:
            # Procurement-only OWN scope may select shared master references;
            # it does not authorize editing those masters.
            unrestricted_reference = True
            continue
        if kind == DataScope.ScopeType.CUSTOM:
            if not isinstance(config, dict):
                raise PermissionDenied("仓库自定义范围配置无效。")
            if set(config) == {"supplier_ids"}:
                values = config["supplier_ids"]
                if not isinstance(values, list) or any(isinstance(value, bool) or not str(value).isdigit() for value in values):
                    raise PermissionDenied("仓库自定义范围配置无效。")
                unrestricted_reference = True
                continue
            if set(config) == {"warehouse_ids"}:
                allowed = config["warehouse_ids"]
                if not isinstance(allowed, list) or any(isinstance(value, bool) or not str(value).isdigit() for value in allowed):
                    raise PermissionDenied("仓库自定义范围配置无效。")
                ids.update(int(value) for value in allowed)
                continue
            raise PermissionDenied("仓库自定义范围配置无效。")
        elif kind != DataScope.ScopeType.OWN:
            raise PermissionDenied("仓库档案数据范围不支持。")
    return query if unrestricted_reference else query.filter(pk__in=ids)


def can_maintain_warehouse(actor, pk=None):
    try:
        scopes = _scopes(actor, MANAGE)
    except PermissionDenied:
        return False
    all_scope = any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes)
    if pk is None:
        return all_scope
    if all_scope:
        return warehouse_refs(actor, MANAGE).filter(pk=pk).exists()
    for scope in scopes:
        config = scope.get("config") or {}
        if not isinstance(config, dict):
            continue
        ids = config.get("warehouse_ids")
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM and set(config) == {"warehouse_ids"} and isinstance(ids, list) and all(str(v).isdigit() and not isinstance(v, bool) for v in ids) and pk in {int(v) for v in ids}:
            return True
    return False


def warehouse_archive_data(obj, actor, *, can_manage=None, wms_mappings=None):
    from apps.integrations.models import WarehouseAuthorization
    if wms_mappings is None:
        wms_mappings = list(WarehouseAuthorization.objects.filter(tenant_id=actor.tenant_id, warehouse_id=obj.pk,
            status__in=["active", "authorized"]).order_by("id"))
    return {
        "id": obj.pk, "version": obj.supply_version, "code": obj.code, "name": obj.name,
        "country_code": obj.country_code, "warehouse_type": obj.warehouse_type,
        "service_platform_id": obj.service_platform_id,
        "service_platform_name": obj.service_platform.name if obj.service_platform_id else "",
        "status": obj.status, "address": obj.address, "region": obj.region,
        "legacy_codes": obj.legacy_codes, "notes": obj.notes,
        "can_manage": can_maintain_warehouse(actor, obj.pk) if can_manage is None else can_manage,
        "wms_mappings": [{"provider": mapping.provider, "external_warehouse_code": mapping.external_warehouse_code,
                           "external_warehouse_region": mapping.external_warehouse_region, "status": mapping.status} for mapping in wms_mappings],
    }


def _manage_flags(actor, warehouse_ids):
    try:
        scopes = _scopes(actor, MANAGE)
    except PermissionDenied:
        return set()
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return set(warehouse_ids)
    editable = set()
    for scope in scopes:
        config = scope.get("config") or {}
        if not isinstance(config, dict):
            continue
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM or set(config) != {"warehouse_ids"}:
            continue
        values = config["warehouse_ids"]
        if isinstance(values, list) and all(not isinstance(value, bool) and str(value).isdigit() for value in values):
            editable.update(int(value) for value in values)
    return editable.intersection(warehouse_ids)


def _warehouse_page_data(rows, actor):
    from apps.integrations.models import WarehouseAuthorization
    ids = [obj.pk for obj in rows]
    mappings = {warehouse_id: [] for warehouse_id in ids}
    for mapping in WarehouseAuthorization.objects.filter(tenant_id=actor.tenant_id, warehouse_id__in=ids,
            status__in=["active", "authorized"]).order_by("id"):
        mappings.setdefault(mapping.warehouse_id, []).append(mapping)
    manageable = _manage_flags(actor, ids)
    return [warehouse_archive_data(obj, actor, can_manage=obj.pk in manageable,
        wms_mappings=mappings.get(obj.pk, [])) for obj in rows]


def _audit_data(obj):
    return {key: getattr(obj, key) for key in ("code", "name", "country_code", "warehouse_type", "service_platform_id", "status", "address", "region", "legacy_codes", "notes")}


@transaction.atomic
def save_warehouse_archive(actor, payload, *, pk=None, idempotency_key):
    if not actor.is_active:
        raise PermissionDenied("需要有效的内部采购账号。")
    require_internal_supply_permission(actor, MANAGE)
    _key(idempotency_key)
    digest_data = {"id": pk, "values": payload}
    prior = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, aggregate_type="warehousemaster", action="archive_saved", request_key=idempotency_key).first()
    if prior:
        if prior.request_hash != request_hash(digest_data):
            raise ValidationError("此请求编号已用于不同内容。")
        obj = warehouse_refs(actor, MANAGE).filter(pk=prior.aggregate_id).select_related("service_platform").first()
        if not obj:
            raise NotFound("仓库不可访问。")
        return obj

    Tenant.objects.select_for_update().get(pk=actor.tenant_id)
    values = dict(payload)
    expected = values.pop("expected_version", None)
    if pk:
        if not can_maintain_warehouse(actor, pk):
            raise PermissionDenied("需要全部范围或该仓库的明确授权才能维护仓库档案。")
        obj = warehouse_refs(actor, MANAGE).select_for_update().filter(pk=pk).select_related("service_platform").first()
        if obj is None:
            raise NotFound("仓库不可访问。")
        if expected != obj.supply_version:
            raise ValidationError("仓库资料已改变，请刷新后再编辑。")
        before = _audit_data(obj)
        allowed = {"name", "address", "region", "legacy_codes", "notes", "status"}
        if set(values) - allowed:
            raise ValidationError("现有仓库的系统编码、国家、类型和服务平台不可在采购档案中修改。")
    else:
        if not can_maintain_warehouse(actor):
            raise PermissionDenied("新增共享仓库档案需要全部数据范围。")
        obj = WarehouseMaster(tenant=actor.tenant)
        before = None
        allowed = {"code", "name", "country_code", "warehouse_type", "service_platform_id", "address", "region", "legacy_codes", "notes", "status"}
        if set(values) - allowed:
            raise ValidationError("仓库档案包含不允许的字段。")

    serializer = WarehouseArchiveInput(data=values, context={"actor": actor, "instance": obj if pk else None}, partial=bool(pk))
    serializer.is_valid(raise_exception=True)
    for name, value in serializer.validated_data.items():
        if name == "service_platform":
            obj.service_platform = value
        else:
            setattr(obj, name, value)
    obj.tenant = actor.tenant
    obj.full_clean()
    with domain_write():
        obj.save()
        after = _audit_data(obj)
        BusinessEvent.objects.create(tenant=actor.tenant, created_by=actor, aggregate_type="warehousemaster",
            aggregate_id=obj.pk, aggregate_version=obj.supply_version, action="archive_saved",
            request_key=idempotency_key, request_hash=request_hash(digest_data),
            payload={"before": before, "after": after})
    return obj


def warehouse_options(actor):
    _scopes(actor, VIEW)
    country_rows = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, status=StatusChoices.ACTIVE).order_by("name", "code")
    countries = []
    seen = set()
    for row in country_rows:
        if row.country_code and row.country_code.upper() not in seen:
            seen.add(row.country_code.upper())
            countries.append({"code": row.code, "name": row.name, "country_code": row.country_code})
    platforms = PlatformMaster.objects.filter(tenant_id=actor.tenant_id, status=StatusChoices.ACTIVE,
        platform_type__in=WAREHOUSE_TYPE_TO_PLATFORM_TYPE.values()).order_by("name", "code")
    return {"countries": countries, "service_platforms": [{"id": row.pk, "code": row.code, "name": row.name, "platform_type": row.platform_type} for row in platforms]}


def _request_key(request):
    value = request.headers.get("Idempotency-Key", "")
    try:
        return _key(value)
    except ValidationError as exc:
        raise APIValidationError(str(exc))


def _validated_write(request, *, pk=None):
    payload = request.data
    if not isinstance(payload, dict):
        raise APIValidationError("仓库档案内容必须是对象。")
    allowed = ({"expected_version", "name", "address", "region", "legacy_codes", "notes", "status"}
               if pk else {"code", "name", "country_code", "warehouse_type", "service_platform_id", "address", "region", "legacy_codes", "notes", "status"})
    forbidden = set(payload) - allowed
    if forbidden:
        raise APIValidationError({name: "字段不允许在仓库档案接口中提交。" for name in sorted(forbidden)})
    if pk and "expected_version" not in payload:
        raise APIValidationError({"expected_version": "编辑仓库时必须提供当前版本。"})
    # Keep the service layer's stable JSON representation, including the ID
    # spelling consumed by its digest and audit record.
    values = dict(payload)
    return values


from .views import InternalAPI, _page


class WarehouseArchives(InternalAPI):
    def get(self, request):
        try:
            limit, offset = int(request.query_params.get("limit", 20)), int(request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            raise APIValidationError("分页参数须为整数。")
        if limit < 1 or limit > 100 or offset < 0:
            raise APIValidationError("limit 须为 1–100，offset 须为非负整数。")
        query = warehouse_refs(request.user).select_related("service_platform").order_by("code")
        search = request.query_params.get("search", "").strip().casefold()
        country = request.query_params.get("country_code", "").strip()
        status = request.query_params.get("status", "").strip()
        if country:
            query = query.filter(country_code__iexact=country)
        if status:
            if status not in StatusChoices.values:
                raise APIValidationError({"status": "状态无效。"})
            query = query.filter(status=status)
        if search:
            matches, count = [], 0
            for obj in query.iterator(chunk_size=500):
                if (search in obj.code.casefold() or search in obj.name.casefold()
                        or any(search in value.casefold() for value in (obj.legacy_codes if isinstance(obj.legacy_codes, list) else []) if isinstance(value, str))):
                    if offset <= count < offset + limit:
                        matches.append(obj)
                    count += 1
            rows, total = matches, count
        else:
            total = query.count()
            rows = list(query[offset:offset + limit])
        data = _warehouse_page_data(rows, request.user)
        return Response({"data": data, "count": total, "limit": limit, "offset": offset,
                         "can_create": can_maintain_warehouse(request.user)})

    def post(self, request):
        values = _validated_write(request)
        obj = save_warehouse_archive(request.user, values, idempotency_key=_request_key(request))
        return Response({"data": warehouse_archive_data(obj, request.user)}, status=201)


class WarehouseArchiveDetail(InternalAPI):
    def patch(self, request, pk):
        values = _validated_write(request, pk=pk)
        obj = save_warehouse_archive(request.user, values, pk=pk, idempotency_key=_request_key(request))
        return Response({"data": warehouse_archive_data(obj, request.user)})


class WarehouseArchiveOptions(InternalAPI):
    def get(self, request):
        return Response({"data": warehouse_options(request.user)})
