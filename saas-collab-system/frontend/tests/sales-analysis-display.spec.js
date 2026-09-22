import { mount, flushPromises } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import Phase3AnalyticsPage from '../src/components/Phase3AnalyticsPage.vue';

const stubs = {
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<label><slot /></label>' },
  'el-button': { template: '<button><slot /></button>' },
  'el-date-picker': true,
  'el-select': { template: '<select><slot /></select>' },
  'el-option': true,
  'el-alert': true,
  'el-progress': true,
  'el-tag': { template: '<span><slot /></span>' },
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': true,
  'el-pagination': true,
  'el-empty': true,
};

describe('经营分析指标中文显示', () => {
  it('translates legacy English metrics and formats money, counts and rates', async () => {
    const loader = vi.fn().mockResolvedValue({ success: true, data: {
      api_status: 'connected', quality: {}, results: [],
      metrics: [
        { code: 'gross_sales', label: 'Sales', value: '606793', unit: 'PHP' },
        { code: 'average_order_value', label: 'Average order value', value: '590.26556420233463035019', unit: 'PHP' },
        { code: 'order_count', label: 'Orders', value: '1028', unit: 'orders' },
        { code: 'refund_rate', label: 'Refund rate', value: '0.01234', unit: 'ratio' },
      ],
    } });
    const wrapper = mount(Phase3AnalyticsPage, {
      props: { title: '销售分析', loader },
      global: { stubs },
    });
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain('销售额');
    expect(text).toContain('平均订单金额');
    expect(text).toContain('606,793.00PHP');
    expect(text).toContain('590.27PHP');
    expect(text).toContain('1,028单');
    expect(text).toContain('1.23%');
    expect(text).not.toContain('Average order value');
    expect(text).not.toContain('590.26556420233463035019');
    wrapper.unmount();
  });
});
