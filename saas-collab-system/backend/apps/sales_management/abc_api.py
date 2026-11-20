from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from apps.commerce import country_decisions as domain
from apps.masterdata.models import InventoryABCRun, InventoryObservationSettings, CountrySiteMaster, StoreMaster
from apps.permissions.ui_p2_scopes import require_all_scope
from .decision_api import CountryDecisionAPI
from .abc_access import ABC_POLICY_VERSION, published_run


class InventoryABCView(CountryDecisionAPI):
    write_permission_code = "masterdata.settings.manage"

    def get(self, request):
        country_id = serializers.IntegerField(min_value=1).run_validation(request.query_params.get("country_id"))
        country = domain.country_for(request.user, country_id)
        _, meta = published_run(request.user, country)
        return Response({"data": meta})

    @transaction.atomic
    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        country_id = serializers.IntegerField(min_value=1).run_validation(request.data.get("country_id"))
        country = domain.country_for(request.user, country_id)
        if not StoreMaster.objects.filter(tenant=request.user.tenant, country_code__iexact=country.country_code, status="active").exists():
            raise serializers.ValidationError("该国家暂无可计算的销售店铺。")
        CountrySiteMaster.objects.select_for_update().get(pk=country.pk, tenant=request.user.tenant)
        settings = InventoryObservationSettings.objects.filter(tenant=request.user.tenant).first()
        if settings and not settings.abc_enabled:
            raise serializers.ValidationError("请先在基础档案设置中启用 ABC 分类。")
        pending = InventoryABCRun.objects.filter(tenant=request.user.tenant, country=country, status__in=["queued", "building"]).order_by("-pk").first()
        if not pending:
            cutoff = timezone.now().astimezone(ZoneInfo(country.timezone)).date() - timedelta(days=1)
            pending = InventoryABCRun.objects.create(tenant=request.user.tenant, country=country, cutoff_date=cutoff, config={"source": "manual", "requested_by": request.user.pk, "classification_basis": "composite", "policy_version": ABC_POLICY_VERSION})
        return Response({"data": {"id": pending.pk, "status": pending.status}})
