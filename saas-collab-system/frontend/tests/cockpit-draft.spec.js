import { describe, expect, it } from 'vitest';
import { stageCockpitDraft, consumeCockpitDraft } from '../src/utils/cockpitDraft';
const input = () => ({ parameters: { country_id: 1, source_kind: 'cycle', sales_start: '2026-09-01', sales_end: '2026-09-30', target_stock_sales_ratio: 1, include_in_transit: true }, rows: [{ sku_id: 5, sku: 'NEW', legacy_sku_code: 'OLD', suggested_quantity: 7 }] });
describe('cockpit draft handoff', () => {
 it('keeps a one-use copy and requires recalculation on receiving page', () => { const data=input();stageCockpitDraft(1,data,100);data.rows[0].suggested_quantity=99;const result=consumeCockpitDraft(1,101);expect(result.lines[0]).toMatchObject({sku_id:5,quantity:7,legacy_sku_code:'OLD'});expect(result.preview_token).toBeUndefined();expect(consumeCockpitDraft(1,102)).toBeNull(); });
 it('does not expose pending products to a switched account or expired navigation', () => { stageCockpitDraft(1,input(),100);expect(consumeCockpitDraft(2,101)).toBeNull();stageCockpitDraft(1,input(),100);expect(consumeCockpitDraft(1,100+15*60*1000+1)).toBeNull(); });
 it('binds handoff to tenant and active membership as well as account',()=>{stageCockpitDraft({id:1,tenant_id:1,active_membership_id:2},input(),100);expect(consumeCockpitDraft({id:1,tenant_id:1,active_membership_id:3},101)).toBeNull();stageCockpitDraft({id:1,tenant_id:1},input(),100);expect(consumeCockpitDraft({id:1,tenant_id:2},101)).toBeNull();});
 it('rejects repeated or unknown/zero suggested quantities', () => { const data=input();data.rows.push({...data.rows[0]});expect(()=>stageCockpitDraft(1,data)).toThrow();for(const value of [null,0,-1,1.5]) {data.rows=[{sku_id:5,suggested_quantity:value}];expect(()=>stageCockpitDraft(1,data)).toThrow();} });
});
