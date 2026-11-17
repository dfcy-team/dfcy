import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import Hourly from '../src/views/sales-management/BoardHourlyTrend.vue';
import Recent from '../src/views/sales-management/BoardRecentTrend.vue';

describe('board pointer tooltips', () => {
  for (const [name, component, props] of [
    ['hourly', Hourly, { current: [{date:'00:00',sales_amount:'12.345'}], previous: [], metric:'sales_amount',unit:'CNY' }],
    ['recent', Recent, { rows:[{date:'2026-11-16',sales_amount:'12.345',order_count:2}],currency:'CNY' }],
  ]) it(name + ' follows pointer, shows crosshair axes, and hides on leave', async () => {
    const wrapper = mount(component, { props });
    await wrapper.find('rect[tabindex]').trigger('pointerenter', {clientX:100,clientY:100});
    expect(wrapper.find('[role="tooltip"]').attributes('style')).toContain('left: 116px');
    expect(wrapper.find('.chart-crosshair').exists()).toBe(true);
    expect(wrapper.find('.chart-crosshair').text()).toContain(name === 'hourly' ? '00:00' : '11-16');
    await wrapper.find('svg').trigger('pointermove',{clientX:window.innerWidth-10,clientY:window.innerHeight-10});
    expect(wrapper.find('[role="tooltip"]').attributes('style')).not.toContain('left: 116px');
    const left = parseFloat(wrapper.find('[role="tooltip"]').element.style.left);
    expect(left + 320).toBeLessThan(window.innerWidth);
    await wrapper.find('svg').trigger('pointerleave');
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    wrapper.unmount();
  });
});


describe('recent shipped order series', () => {
  it('shows shipped counts in bars, pointer tooltip and daily values, preserving unavailable values', async () => {
    const wrapper = mount(Recent, { props: { rows: [
      { date: '2026-11-16', sales_amount: '12.345', order_count: 8, shipped_order_count: 3 },
      { date: '2026-11-17', sales_amount: '5', order_count: 4 },
    ], currency: 'CNY' } });
    expect(wrapper.find('.legend').text()).toContain('已同步发货订单');
    expect(wrapper.findAll('.legend .shipped')).toHaveLength(1);
    const bars = wrapper.findAll('rect').filter((bar) => bar.element.tagName.toLowerCase() === 'rect' && bar.find('title').exists());
    expect(bars.map((bar) => bar.find('title').text())).toContain('2026-11-16 已发货订单：3');
    expect(bars.some((bar) => bar.attributes('fill') === '#36b8e8')).toBe(true);
    await wrapper.find('rect[tabindex]').trigger('pointerenter', { clientX: 100, clientY: 100 });
    expect(wrapper.find('[role="tooltip"]').text()).toContain('已发货订单 3');
    await wrapper.find('details summary').trigger('click');
    expect(wrapper.find('table').text()).toContain('3');
    expect(wrapper.find('table').text()).toContain('暂无已拉取数据');
    wrapper.unmount();
  });
});
