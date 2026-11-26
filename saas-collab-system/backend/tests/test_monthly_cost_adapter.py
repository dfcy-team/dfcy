from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from apps.finance.monthly_cost_adapter import select_monthly_cost

def test_missing_month_never_falls_back_after_cutover():
    legacy=object();index={"cutover":"2026-11","rows":{}}
    assert select_monthly_cost(index,1,2,"2026-10-20",legacy) is legacy
    assert select_monthly_cost(index,1,2,"2026-11-20",legacy) is None

def test_valid_zero_month_cost_is_used():
    row=SimpleNamespace(pk=9,version_no=2,unit_cost=Decimal("0"),is_complete=True,month=date(2026,11,1),status="estimated")
    index={"cutover":"2026-11","rows":{(1,2,"2026-11"):row}}
    value=select_monthly_cost(index,1,2,"2026-11-20")
    assert value.confirmed_cost==0
    assert value.monthly_cost_status=="estimated"
    assert value.pk is None

def test_disabled_uses_existing_cost():
    legacy=object();assert select_monthly_cost(None,1,2,"2026-11-20",legacy) is legacy
