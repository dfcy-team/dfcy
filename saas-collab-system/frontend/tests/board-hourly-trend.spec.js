import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import Chart from '../src/views/sales-management/BoardHourlyTrend.vue';
describe('hourly comparison', () => {
  it('renders hourly bars and cumulative values without creating missing hours', async () => {
    const wrapper = mount(Chart, { props: { current: [{date:'01:00',sales_amount:'10',order_count:1},{date:'03:00',sales_amount:'20',order_count:2}], previous: [{date:'01:00',sales_amount:'5',order_count:3}], metric:'sales_amount',unit:'PHP' } });
    expect(wrapper.findAll('rect')).toHaveLength(3);
    expect(wrapper.findAll('circle')).toHaveLength(2);
    expect(wrapper.text()).toContain('今日累计：30 PHP');
    expect(wrapper.text()).toContain('昨日 01:00：5 PHP');
    expect(wrapper.text()).toContain('23:00');
    await wrapper.setProps({metric:'order_count',unit:'单'});
    expect(wrapper.text()).toContain('今日累计：3 单');
    expect(wrapper.find('svg').attributes('aria-label')).toContain('订单量');
  });
});
