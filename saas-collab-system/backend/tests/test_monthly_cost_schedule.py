from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from django.test import override_settings
from apps.products.monthly_cost_schedule import prepare_actor,finalize_ready_months

def test_disabled_schedule_does_no_work():
 with override_settings(MONTHLY_PRODUCT_COST_ENABLED=False):
  assert prepare_actor.run(1)=={"status":"disabled"}
  assert finalize_ready_months.run(1)["status"]=="disabled"

def test_daily_pipeline_recalculates_prior_then_current_month_and_finalizes_prior():
 with override_settings(MONTHLY_PRODUCT_COST_ENABLED=True,SUPPLY_MONTHLY_COST_JOBS_ENABLED=False,MONTHLY_PRODUCT_COST_CUTOVER_MONTH="2025-04"),patch("django.utils.timezone.localdate",return_value=date(2025,5,10)),patch("apps.accounts.models.CustomUser.objects.get",return_value=SimpleNamespace(pk=9,tenant_id=3)),patch("apps.products.tasks.aggregate_monthly_product_cost_sources.run",return_value={"status":"pending_review","written":1}) as calculate,patch("apps.products.monthly_cost_schedule.finalize_ready_months.run",return_value={"finalized":1}) as finalize:
  result=prepare_actor.run(9)
  assert [call.args[1] for call in calculate.call_args_list]==["2025-04-01","2025-05-01"]
  finalize.assert_called_once_with(3)
  assert result["status"]=="completed"

def test_missing_cutover_is_explicit_configuration_state():
 with override_settings(MONTHLY_PRODUCT_COST_ENABLED=True,SUPPLY_MONTHLY_COST_JOBS_ENABLED=False,MONTHLY_PRODUCT_COST_CUTOVER_MONTH=""),patch("apps.accounts.models.CustomUser.objects.get",return_value=SimpleNamespace(pk=9,tenant_id=3)):
  assert prepare_actor.run(9)["status"]=="pending_configuration"
