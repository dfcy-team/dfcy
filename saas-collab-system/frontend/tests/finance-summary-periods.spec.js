import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const { periodRange, periodOptions, datedFact, inPeriod }=require('../../backend/apps/finance/summary_periods.cjs');

describe('财务账期内周／半月归期',()=>{
 it('自然周周一到周日，可跨月、跨年，不接受伪造日期',()=>{
  expect(periodRange('week','2026-08-31')).toEqual({from:'2026-08-31',to:'2026-09-06'});
  expect(periodRange('week','2026-12-28').to).toBe('2027-01-03');
  expect(()=>periodRange('week','2026-09-01')).toThrow();
  expect(()=>periodRange('half_month','2026-02-30')).toThrow();
 });
 it('半月为1—15日、16日—月底；闰年正确',()=>{
  expect(periodRange('half_month','2026-09-01')).toEqual({from:'2026-09-01',to:'2026-09-15'});
  expect(periodRange('half_month','2026-09-16').to).toBe('2026-09-30');
  expect(periodRange('half_month','2028-02-16').to).toBe('2028-02-29');
 });
 it('每个账期保留完整周期选项，也保留跨账期的真实日期',()=>{
  const options=periodOptions('2026-09',['2026-08-18',null,'2026-09']);
  expect(options.week.some(r=>r.value==='2026-08-17')).toBe(true);
  expect(options.week.some(r=>r.value==='2026-08-31')).toBe(true);
  expect(options.half_month.map(r=>r.value)).toEqual(['2026-09-16','2026-09-01','2026-08-16']);
 });
 it('明确缺日期不退回结算日；月度合成广告日期不伪装成月初',()=>{
  expect(datedFact({date:'2026-09-10',statistics_date:null},new Map()).period_date).toBeNull();
  expect(datedFact({date:'2026-09',source_id:'warehouse:1'},new Map()).period_date).toBeNull();
  expect(datedFact({date:'2026-09-01',source_id:'hierarchy-ad:1'},new Map()).period_date).toBeNull();
 });
 it('公共费用保持已分摊金额，用关联订单本账期首次有效结算日归期',()=>{
  const first=new Map([['1|o|PHP','2026-09-18']]);
  const f={source_id:'sales-share:ad:o',store_id:1,external_order_id:'o',currency:'PHP',date:'2026-09-01',amount:'-1.000001',hierarchy_allocation:{}};
  const dated=datedFact(f,first);
  expect(dated.period_date).toBe('2026-09-18');expect(dated.amount).toBe(f.amount);expect(f.date).toBe('2026-09-01');
  expect(inPeriod(dated,'half_month','2026-09-16')).toBe(true);
  expect(inPeriod(dated,'half_month','undated')).toBe(false);
 });
});
