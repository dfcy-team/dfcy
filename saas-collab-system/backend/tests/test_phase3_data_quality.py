from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.products.models import ProductSKU, ProductSPU
from apps.replenishment.models import ReplenishmentRecommendation
from apps.reports.models import ReportExportRequest
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_phase3_data_quality_passes_on_clean_database():
    call_command("check_phase3_data_quality")


@pytest.mark.django_db
def test_phase3_data_quality_rejects_expired_active_recommendation():
    tenant = Tenant.objects.create(name="Demo quality tenant", code="phase3-quality")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="DEMO-SPU", product_name="Demo product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="DEMO-SKU")
    ReplenishmentRecommendation.objects.create(
        tenant=tenant,
        spu=spu,
        sku=sku,
        available_stock=0,
        in_transit_stock=0,
        average_daily_sales=1,
        safety_stock_days=3,
        supplier_lead_days=7,
        replenishment_cycle_days=7,
        suggested_quantity=17,
        suggested_date=timezone.localdate() - timedelta(days=1),
        confidence="1.0000",
        reason_code="demo_expired",
        reason_detail="Demo-only expired recommendation.",
        source_summary={"source": "demo"},
        formula_version="replenishment-v1",
        dedup_key="phase3-quality-expired",
    )

    with pytest.raises(CommandError, match="found 1 issue"):
        call_command("check_phase3_data_quality")


@pytest.mark.django_db
def test_phase3_data_quality_never_prints_sensitive_export_values():
    tenant = Tenant.objects.create(name="Demo export tenant", code="phase3-quality-export")
    user = CustomUser.objects.create_user(username="quality-export-user", tenant=tenant, user_type="internal")
    export_request = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.ANALYTICS_SUMMARY,
        requested_by=user,
        data_scope=[],
        filters={"api_key": "not-a-real-secret-value"},
        status=ReportExportRequest.Status.REJECTED,
        rejection_reason="demo_quality_fixture",
    )
    export_request._export_service_write = True
    export_request.save()
    stderr = StringIO()

    with pytest.raises(CommandError, match="found 2 issue"):
        call_command("check_phase3_data_quality", stderr=stderr)

    output = stderr.getvalue()
    assert "sensitive_field_leakage" in output
    assert "export_without_audit" in output
    assert "not-a-real-secret-value" not in output
