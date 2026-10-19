import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { toRaw } from 'vue';
import ReportResult from '../src/views/reports/ReportResult.vue';

describe('readable report identities preserve drill-through keys', () => {
  it.each(['card', 'bar', 'pivot'])('shows names in %s while drilling with original IDs and codes', async chart => {
    const row = { store_id: 42, sku: 'OLD-LG-70', units: 3 };
    const wrapper = mount(ReportResult, {
      props: {
        result: { rows: [row], columns: [], dimension_labels: { store_id: { 42: '菲律宾运营店' }, sku: { 'OLD-LG-70': '浅灰毯子 · OLD-LG-70' } } },
        config: { dimensions: ['store_id', 'sku'], metrics: ['units'], chart, pivot: chart === 'pivot' ? 'sku' : '' },
        dataset: { dimensions: [{ key: 'store_id', label: '店铺' }, { key: 'sku', label: '商品' }], metrics: [{ key: 'units', label: '销量' }] }
      },
      global: { stubs: { 'el-table': true, 'el-empty': true } }
    });
    expect(wrapper.text()).toContain('菲律宾运营店');
    expect(wrapper.text()).toContain('浅灰毯子 · OLD-LG-70');
    await wrapper.find(chart === 'card' ? '.metric-cards button' : chart === 'bar' ? '.chart-legend button' : 'tbody button').trigger('click');
    expect(toRaw(wrapper.emitted('drill')[0][0])).toEqual(row);
    expect(row.store_id).toBe(42);
    wrapper.unmount();
  });
});
