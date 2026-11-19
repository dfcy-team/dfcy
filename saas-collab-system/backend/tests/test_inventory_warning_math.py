import unittest
from datetime import date
from apps.alerts.warning_math import assess_sku, assess_spu

class WarningMathTests(unittest.TestCase):
    def calc(self, **kwargs):
        return assess_sku(**dict(stock=10,daily_sales=2,arrivals=[],today=date(2026,11,19),horizon_days=10,**kwargs))
    def test_late_delivery_does_not_hide_gap(self):
        r=assess_sku(stock=10,daily_sales=2,arrivals=[{'quantity':100,'expected_date':'2026-11-27'}],today=date(2026,11,19),horizon_days=10)
        self.assertEqual(r['first_shortage_date'],'2026-11-25')
        self.assertEqual(r['maximum_shortage_quantity'],4)
    def test_unknown_and_overdue_never_assumed_received(self):
        r=assess_sku(stock=0,daily_sales=2,arrivals=[{'quantity':100,'expected_date':None},{'quantity':50,'expected_date':'2026-11-18'}],today=date(2026,11,19),production_unshipped=30)
        self.assertEqual(r['first_shortage_date'],'2026-11-19')
        self.assertEqual(r['unknown_arrival_quantity'],'100')
        self.assertEqual(r['overdue_quantity'],'50')
    def test_missing_sales_is_not_zero_sales(self):
        r=assess_sku(stock=10,daily_sales=None,arrivals=[],today=date(2026,11,19),sales_complete=False)
        self.assertEqual(r['state'],'unavailable');self.assertEqual(r['warnings'],[])
    def test_new_sku_not_slow_moving(self):
        r=assess_sku(stock=10,daily_sales=0,arrivals=[],today=date(2026,11,19),first_sale_date='2026-11-18')
        self.assertIn('new_product_observation',r['warnings']);self.assertNotIn('stock_without_sales',r['warnings'])
    def test_same_day_arrival_usable(self):
        r=assess_sku(stock=1,daily_sales=2,arrivals=[{'quantity':100,'expected_date':'2026-11-19'}],today=date(2026,11,19),horizon_days=10)
        self.assertIsNone(r['first_shortage_date'])
    def test_unknown_first_sale_is_not_established(self):
        r=assess_sku(stock=100,daily_sales=0,arrivals=[],today=date(2026,11,19))
        self.assertNotIn('stock_without_sales',r['warnings'])
    def test_new_observation_survives_unknown_inventory(self):
        r=assess_sku(stock=None,daily_sales=0,arrivals=[],today=date(2026,11,19),first_sale_date='2026-11-18')
        self.assertIn('new_product_observation',r['warnings'])
    def test_activity_changes_forecast(self):
        r=assess_sku(stock=10,daily_sales=2,arrivals=[],today=date(2026,11,19),horizon_days=3,activity_start='2026-11-20',activity_end='2026-11-22',activity_factor=2)
        self.assertEqual(r['first_shortage_date'],'2026-11-22')
    def test_partial_supply_keeps_factual_delays(self):
        r=assess_sku(stock=10,daily_sales=2,arrivals=[{'quantity':5,'expected_date':'2026-11-18'}],today=date(2026,11,19),supply_complete=False)
        self.assertIn('supply_overdue',r['warnings']);self.assertEqual(r['state'],'unavailable');self.assertIsNone(r['first_shortage_date'])
    def test_planned_today_arrival_does_not_erase_current_stockout(self):
        r=assess_sku(stock=0,daily_sales=2,arrivals=[{'quantity':100,'expected_date':'2026-11-19'}],today=date(2026,11,19),horizon_days=10)
        self.assertEqual(r['first_shortage_date'],'2026-11-19');self.assertEqual(r['maximum_shortage_quantity'],0)
    def test_exact_daily_ratio_has_no_phantom_gap(self):
        r=assess_sku(stock=2,daily_sales='0.6666666666666666666666666667',daily_ratio=(2,3),arrivals=[],today=date(2026,11,19),horizon_days=3)
        self.assertIsNone(r['first_shortage_date']);self.assertEqual(r['maximum_shortage_quantity'],0)
    def test_key_variant_and_ties(self):
        rows=[{'sku_id':1,'sales_quantity':50,'warning':{'warnings':['forecast_stockout']}},{'sku_id':2,'sales_quantity':25},{'sku_id':3,'sales_quantity':25}]
        r=assess_spu(rows);self.assertEqual(r['key_sku_ids'],[1,2,3]);self.assertEqual(r['key_shortage_sales_share'],'0.5')
if __name__=='__main__':unittest.main()
