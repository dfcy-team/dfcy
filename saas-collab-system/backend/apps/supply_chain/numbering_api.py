"""Internal API for tenant business document numbering rules."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.masterdata.models import CountrySiteMaster
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from apps.purchasing.supply_permissions import require_internal_supply_permission
from apps.tenants.models import Tenant
from .dates import business_date
from .models import BusinessEvent, DocumentNumberRule, domain_write
from .numbering import DEFAULTS, DEFAULT_RULE, KINDS, RULE_FIELDS, preview, validate_rule
from .permissions import MANAGE, VIEW
from .views import InternalAPI


class RuleFields(serializers.Serializer):
    enabled = serializers.BooleanField()
    include_country = serializers.BooleanField()
    country_prefixes = serializers.DictField(child=serializers.CharField(allow_blank=False), required=True)
    prefix = serializers.CharField()
    date_format = serializers.CharField()
    separator = serializers.CharField()
    sequence_width = serializers.IntegerField()
    reset_period = serializers.CharField()

    def validate(self, attrs):
        try:
            result = validate_rule({**attrs, "tenant_id": self.context["tenant_id"]})
            return {**attrs, **result}
        except DjangoValidationError as exc:
            detail = getattr(exc, "message_dict", None) or exc.messages
            raise serializers.ValidationError(detail)


class PreviewInput(RuleFields):
    country_code = serializers.CharField(required=False, allow_blank=True, default="")


class SaveInput(RuleFields):
    expected_version = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(min_length=1, max_length=500, trim_whitespace=True)


def _rule_data(rule, kind):
    if not rule:
        return {**DEFAULT_RULE, "prefix": DEFAULTS[kind][0]}
    return {field: getattr(rule, field) for field in RULE_FIELDS}


def _history(rule):
    if not rule:
        return []
    events = BusinessEvent.objects.filter(tenant_id=rule.tenant_id, aggregate_type="documentnumberrule",
        aggregate_id=rule.pk, action="number_rule_updated").order_by("-created_at", "-pk")[:10]
    return [{"version": event.aggregate_version, "actor": event.created_by.full_name or event.created_by.username,
             "created_at": event.created_at, "reason": event.payload.get("reason", "")} for event in events]


def _country_rows(tenant_id):
    result = {}
    for row in CountrySiteMaster.objects.filter(tenant_id=tenant_id).order_by("country_code", "name").values("country_code", "name"):
        result.setdefault(row["country_code"], row["name"])
    return [{"country_code": code, "name": name} for code, name in result.items()]


def _serialize(kind, rule, tenant_id, countries):
    values = _rule_data(rule, kind)
    sample_country = countries[0]["country_code"] if countries else ""
    if values["include_country"] and not sample_country:
        example = "需先配置国家"
    else:
        try:
            example = preview(kind, values, tenant_id, country_code=sample_country if values["include_country"] else "")["example"]
        except DjangoValidationError as exc:
            example = str(exc)
    return {"kind": kind, "label": KINDS[kind], "version": rule.version if rule else 0,
        **values, "example": example, "legacy_description": DEFAULTS[kind][1],
        "updated_at": rule.updated_at if rule else None, "history": _history(rule)}


def _can_manage(user):
    if not user or not user.is_active:
        return False
    try:
        require_internal_supply_permission(user, MANAGE)
    except PermissionDenied:
        return False
    scopes = get_permission_data_scopes(user, MANAGE)
    return any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes)


class NumberRules(InternalAPI):
    def get(self, request):
        if not request.user.is_active:
            raise PermissionDenied("需要有效的内部账号。")
        require_internal_supply_permission(request.user, VIEW)
        tenant_id = request.user.tenant_id
        countries = _country_rows(tenant_id)
        rules = {rule.kind: rule for rule in DocumentNumberRule.objects.filter(tenant_id=tenant_id)}
        return Response({"data": {"rules": [_serialize(kind, rules.get(kind), tenant_id, countries) for kind in KINDS],
                         "can_manage": _can_manage(request.user), "business_date": business_date().isoformat(),
                         "countries": [{"code": row["country_code"], "name": row["name"]} for row in countries]}})


class NumberRulePreview(InternalAPI):
    write_permission_code = VIEW

    def post(self, request, kind):
        if not request.user.is_active:
            raise PermissionDenied("需要有效的内部账号。")
        require_internal_supply_permission(request.user, VIEW)
        if kind not in KINDS:
            raise ValidationError("未知单据类型。")
        serializer = PreviewInput(data=request.data, context={"tenant_id": request.user.tenant_id})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = preview(kind, {key: data[key] for key in RULE_FIELDS}, request.user.tenant_id,
                country_code=data.get("country_code", ""))
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages)
        return Response({"data": result})


class NumberRuleDetail(InternalAPI):
    @transaction.atomic
    def patch(self, request, kind):
        user = request.user
        if not user.is_active:
            raise PermissionDenied("需要有效的内部账号。")
        require_internal_supply_permission(user, MANAGE)
        if not any(s["scope_type"] == DataScope.ScopeType.ALL for s in get_permission_data_scopes(user, MANAGE)):
            raise PermissionDenied("修改全租户编号规则需要全部数据范围。")
        if kind not in KINDS:
            raise ValidationError("未知单据类型。")
        serializer = SaveInput(data=request.data, context={"tenant_id": user.tenant_id})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        key = request.headers.get("Idempotency-Key")
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise ValidationError("需要有效的 Idempotency-Key。")
        Tenant.objects.select_for_update().get(pk=user.tenant_id)
        rule = DocumentNumberRule.objects.filter(tenant_id=user.tenant_id, kind=kind).first()
        if rule:
            prior = BusinessEvent.objects.filter(tenant_id=user.tenant_id, aggregate_type="documentnumberrule",
                aggregate_id=rule.pk, action="number_rule_updated", request_key=key).first()
            if prior:
                from .services import _matching_replay, request_hash
                _matching_replay(prior, request_hash(payload))
                return Response({"data": _serialize(kind, rule, user.tenant_id, _country_rows(user.tenant_id))})
        version = rule.version if rule else 0
        if payload["expected_version"] != version:
            raise ValidationError("编号规则已被其他人修改，请刷新后重试。")
        rule_values = {field: payload[field] for field in RULE_FIELDS}
        try:
            validate_rule({**rule_values, "tenant_id": user.tenant_id})
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages)
        old = {field: getattr(rule, field) for field in RULE_FIELDS} if rule else None
        with domain_write():
            if rule:
                for field, value in rule_values.items():
                    setattr(rule, field, value)
                rule.version += 1
                rule.save()
            else:
                rule = DocumentNumberRule.objects.create(tenant=user.tenant, created_by=user,
                    kind=kind, **rule_values)
            from .services import _event
            _event(user, rule, "number_rule_updated", key, payload,
                   audit={"reason": payload["reason"], "old_rule": old, "new_rule": rule_values})
        return Response({"data": _serialize(kind, rule, user.tenant_id, _country_rows(user.tenant_id))})
