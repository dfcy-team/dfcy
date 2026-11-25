import { afterEach, expect, it } from 'vitest';
import { enableAutoUnmount, mount } from '@vue/test-utils';
import Picker from '../src/views/finance/FinancePeriodPicker.vue';
import { calendarDays, periodRange } from '../src/views/finance/financePeriods';
enableAutoUnmount(afterEach);
const render=(extra={})=>mount(Picker,{props:{modelValue:{period_type:'month',month:'2026-11',period:''},coverage:{from:'2026-08-01',to:'2026-11-24'},...extra}});
const open=async w=>w.find('.period-trigger').trigger('click');
const button=(w,text)=>w.findAll('button').find(item=>item.text()===text);
it('合并入口显示维度与区间，打开左侧维度右侧日历，应用前不改变外部筛选',async()=>{
 const w=render();expect(w.findAll('.period-trigger')).toHaveLength(1);await open(w);expect(w.find('[role="dialog"]').exists()).toBe(true);expect(w.findAll('[data-month]')).toHaveLength(12);expect(w.find('footer').text()).toContain('2026-11-01 — 2026-11-30');
 await w.find('[data-month="2026-10"]').trigger('click');expect(w.emitted('update:modelValue')).toBeUndefined();await button(w,'应用').trigger('click');expect(w.emitted('update:modelValue')[0][0]).toEqual({period_type:'month',month:'2026-10',period:''});expect(w.find('[role="dialog"]').exists()).toBe(false);
});
it('取消、Escape和点外部均丢弃尚未应用的选择',async()=>{
 const w=render();await open(w);await button(w,'周度').trigger('click');await button(w,'取消').trigger('click');expect(w.emitted('update:modelValue')).toBeUndefined();
 await open(w);await w.find('[role="dialog"]').trigger('keydown',{key:'Escape'});expect(w.find('[role="dialog"]').exists()).toBe(false);
 await open(w);document.dispatchEvent(new Event('pointerdown'));expect(w.emitted('update:modelValue')).toBeUndefined();
});
it('周历点击跨月日期，选择完整自然周并高亮同周日期',async()=>{
 const w=render();await open(w);await button(w,'周度').trigger('click');await w.find('[data-day="2026-12-01"]').trigger('click');expect(w.find('footer').text()).toContain('2026-11-30 — 2026-12-06');expect(w.find('[data-day="2026-11-30"]').attributes('aria-pressed')).toBe('true');expect(w.find('[data-day="2026-11-29"]').attributes('aria-pressed')).toBe('false');await button(w,'应用').trigger('click');expect(w.emitted('update:modelValue')[0][0]).toEqual({period_type:'week',month:'2026-11',period:'2026-11-30'});
});
it('半月历显示每个月上下半月，月底按实际天数计算',async()=>{
 const w=render();await open(w);await button(w,'半月').trigger('click');expect(w.findAll('[data-half]')).toHaveLength(24);await w.find('[data-half="2026-02-16"]').trigger('click');expect(w.find('footer').text()).toContain('2026-02-16 — 2026-02-28');await button(w,'应用').trigger('click');expect(w.emitted('update:modelValue')[0][0]).toEqual({period_type:'half_month',month:'2026-02',period:'2026-02-16'});
});
it('没有数据或尚未汇总的月份也能选择，超出接入范围明确提示',async()=>{
 const w=render();await open(w);await w.find('[aria-label="下一年"]').trigger('click');await w.find('[data-month="2027-03"]').trigger('click');expect(w.find('footer').text()).toContain('超出已接入日期范围');await button(w,'应用').trigger('click');expect(w.emitted('update:modelValue')[0][0].month).toBe('2027-03');
});
it('保留全部账期和待归期入口',async()=>{
 const w=render();await open(w);await button(w,'全部账期').trigger('click');await button(w,'应用').trigger('click');expect(w.emitted('update:modelValue')[0][0].month).toBe('');
 await open(w);await button(w,'周度').trigger('click');await button(w,'待归期').trigger('click');await button(w,'应用').trigger('click');expect(w.emitted('update:modelValue')[1][0].period).toBe('undated');
});
it('保存中不能打开或应用弹层',async()=>{
 const w=render();await open(w);await w.setProps({disabled:true});expect(w.find('[role="dialog"]').exists()).toBe(false);expect(w.find('.period-trigger').attributes('disabled')).toBeDefined();expect(w.emitted('update:modelValue')).toBeUndefined();
});
it('日历保持周一至周日排列，跨年周和闰年半月范围正确',()=>{
 expect(calendarDays('2026-11')[0]).toBe('2026-10-26');expect(calendarDays('2026-11')).toHaveLength(42);expect(periodRange('week','2026-01-01')).toEqual({from:'2025-12-29',to:'2026-01-04'});expect(periodRange('half_month','2028-02-16')).toEqual({from:'2028-02-16',to:'2028-02-29'});
});
