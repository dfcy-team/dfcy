import json
from datetime import datetime
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from apps.commerce.models import InboundRecord
from apps.integrations.sync_services import run_sync_job
from apps.integrations.models import SyncJob
from tests.test_order_warehouse_lookup import binding, setup_order

pytestmark = pytest.mark.django_db


def test_daily_inbound_import_reuses_receiving_line_and_preserves_raw_header(setup_order, settings):
    settings.WAREHOUSE_BUSINESS_API_ENABLED = True
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse, 'inbound')
    config = auth.integration_config
    config.environment = 'production'
    config.status, config.network_enabled, config.sync_read_enabled = 'verified', True, True
    config.save(update_fields=['environment', 'status', 'network_enabled', 'sync_read_enabled'])
    job = SyncJob.objects.create(tenant=order.tenant, integration_config=config,
        warehouse_authorization=auth, resource_type='inbound', schedule_type='daily',
        is_enabled=True, max_retry_count=0)


    order = {
        "warehouseCode": auth.external_warehouse_code,
        "inboundNo": "IN-1",
        "trackingNoList": ["TRACK-1"],
        "status": 1,
        "receiveStatus": 0,
        "skuList": [{"sku": "A", "count": 3, "receiveCount": None}],
    }
    payload = {"code": 0, "data": {"pageNo": 1, "totalPage": 1, "rows": [order]}}
    client_path = "apps.integrations.readonly_clients.JifengWmsReadonlyClient"
    with (patch("apps.integrations.warehouse_credential_service.require_verified_warehouse"),
          patch("apps.integrations.readonly_clients.get_custody_backend"),
          patch(f"{client_path}.preflight"),
          patch(f"{client_path}._signed_post", return_value=payload)):
        first, _ = run_sync_job(job, idempotency_key="inbound-first")
        assert first.status == "success", first.masked_error_message
        assert first.created_count == 1
        assert first.raw_envelopes.exists()
        assert InboundRecord.objects.get().received_quantity == 0

        order["receiveStatus"] = 2
        order["status"] = 4
        order["receiveLastTime"] = "2026-11-19T07:13:48.536"
        order["skuList"][0]["receiveCount"] = 3
        second, _ = run_sync_job(job, idempotency_key="inbound-second")
        assert second.status == "success", second.masked_error_message
        assert second.updated_count == 1
        assert InboundRecord.objects.get().received_quantity == 3
import json
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.management import call_command


def test_inbound_registration_previews_then_registers_one_daily_job(setup_order, settings):
    settings.WAREHOUSE_BUSINESS_API_ENABLED = True
    order, actor, warehouse = setup_order
    auth = binding(order, actor, warehouse, 'schedule')
    config = auth.integration_config
    config.environment = 'production'
    config.status, config.network_enabled, config.sync_read_enabled = 'verified', True, True
    config.save(update_fields=['environment', 'status', 'network_enabled', 'sync_read_enabled'])

    def register(apply=False):
        stdout = StringIO()
        call_command('register_jifeng_inbound_jobs', tenant_id=actor.tenant_id, actor_id=actor.pk,
                     apply=apply, stdout=stdout)
        return json.loads(stdout.getvalue())[0]

    with (patch('apps.integrations.warehouse_credential_service.require_verified_warehouse'),
          patch('apps.integrations.readonly_clients.get_custody_backend'),
          patch('apps.integrations.readonly_clients.JifengWmsReadonlyClient.preflight')):
        preview = register()
        assert preview['status'] == 'eligible'
        assert not SyncJob.objects.filter(resource_type='inbound').exists()
        next_run = datetime.fromisoformat(preview['next_run_at']).astimezone(ZoneInfo('Asia/Shanghai'))
        assert (next_run.hour, next_run.minute) == (2, 0)
        saved = register(apply=True)
        repeated = register(apply=True)
        assert saved['status'] == 'registered'
        assert repeated['status'] == 'existing' and repeated['job_id'] == saved['job_id']
        assert SyncJob.objects.filter(resource_type='inbound', warehouse_authorization=auth).count() == 1
