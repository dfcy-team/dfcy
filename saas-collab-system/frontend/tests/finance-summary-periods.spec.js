import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const { date,validDate,periodRange, periodOptions, datedFact, inPeriod, periodFilter }=require('../../backend/apps/finance/summary_periods.cjs');

describe('财务账期内周／半月归期',()=>{
 it('日期缓存不共享可变Date，保留闰年、纪元及无效日期规则',()=>{
  expect(validDate('2000-02-29')).toBe(true);expect(validDate('1900-02-29')).toBe(false);
  expect(validDate('2026-02-30')).toBe(false);expect(date('2026-02-30')).toBeNull();
  expect(validDate(null)).toBe(false);expect(validDate('2026-2-01')).toBe(false);
  const first=date('1970-01-01');first.setUTCFullYear(2001);
  expect(date('1970-01-01').getTime()).toBe(0);expect(date('1970-01-01')).not.toBe(first);
  for(let day=0;day<700;day++)expect(validDate(new Date(Date.UTC(2020,0,1+day)).toISOString().slice(0,10))).toBe(true);
  expect(date('1970-01-01').getTime()).toBe(0);expect(validDate('1900-02-29')).toBe(false);
 });
 it('预计算区间保持跨月、待归期和空筛选语义，拒绝非法区间',()=>{
  const rows=[{period_date:'2026-08-31'},{period_date:'2026-09-06'},{period_date:'2026-09-07'},{period_date:null},{period_date:'2026-02-30'}];
  expect(rows.filter(periodFilter('week','2026-08-31'))).toEqual(rows.slice(0,2));
  expect(rows.filter(periodFilter('half_month','undated'))).toEqual(rows.slice(3));
  expect(rows.filter(periodFilter('month',''))).toEqual(rows);
  expect(()=>periodFilter('week','2026-09-01')).toThrow();
 });
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
