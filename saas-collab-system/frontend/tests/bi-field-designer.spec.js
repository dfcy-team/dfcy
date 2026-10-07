import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ReportFieldDesigner from '../src/views/reports/ReportFieldDesigner.vue';

const dataset = { id: 'sales', dimensions: [{ key: 'store_id', label: '店铺' }, { key: 'currency', label: '币种' }, { key: 'platform', label: '平台' }], metrics: [{ key: 'gross_sales', label: '销售额', kind: 'money' }, { key: 'orders', label: '订单数' }], filters: ['date_from', 'store_id'] };
const config = () => ({ dimensions: ['store_id', 'currency'], metrics: ['gross_sales', 'orders'], filters: { store_id: 's1', date_from: '2026-01-01' }, chart: 'bar', chart_metric: 'gross_sales', pivot: '', ordering: '', field_layout: { rows: ['store_id', 'currency'], columns: [], filters: ['date_from', 'store_id'] } });
const mountDesigner = () => mount(ReportFieldDesigner, { props: { dataset, config: config() } });
const transfer = value => ({ getData: type => type === 'application/x-report-field' ? JSON.stringify(value) : '' });

describe('ReportFieldDesigner interactions', () => {
  it('accepts native drop data for a valid dimension and emits updated layout', async () => {
    const wrapper = mountDesigner();
    await wrapper.find('[data-zone="columns"]').trigger('drop', { dataTransfer: transfer({ key: 'platform', kind: 'dimension', dataset: 'sales' }) });
    const next = wrapper.emitted('change').at(-1)[0];
    expect(next.field_layout.columns).toEqual(['platform']);
    expect(next.dimensions).toContain('platform');
    expect(next.chart).toBe('pivot');
  });

  it('rejects native drop data from a different dataset', async () => {
    const wrapper = mountDesigner();
    await wrapper.find('[data-zone="rows"]').trigger('drop', { dataTransfer: transfer({ key: 'sku', kind: 'dimension', dataset: 'inventory' }) });
    expect(wrapper.emitted('change')).toBeUndefined();
    expect(wrapper.emitted('change')).toBeUndefined();
    expect(wrapper.find('[data-zone="rows"]').text()).toContain('店铺');
  });

  it('rejects invalid field kinds on a native drop', async () => {
    const wrapper = mountDesigner();
    await wrapper.find('[data-zone="rows"]').trigger('drop', { dataTransfer: transfer({ key: 'gross_sales', kind: 'metric', dataset: 'sales' }) });
    expect(wrapper.emitted('change')).toBeUndefined();
    expect(wrapper.text()).toContain('无法添加');
  });

  it('removing a filter field also clears its configured value', async () => {
    const wrapper = mountDesigner();
    await wrapper.get('[aria-label="移除开始日期"]').trigger('click');
    expect(wrapper.emitted('change').at(-1)[0].filters).not.toHaveProperty('date_from');
    expect(wrapper.emitted('change').at(-1)[0].field_layout.filters).not.toContain('date_from');
  });

  it('provides button controls equivalent to moving a dimension into columns', async () => {
    const wrapper = mountDesigner();
    await wrapper.get('[aria-label="将店铺移到列"]').trigger('click');
    expect(wrapper.emitted('change').at(-1)[0].field_layout.columns).toEqual(['store_id']);
  });

  it('reports a rejected filter when the drop payload is malformed', async () => {
    const wrapper = mountDesigner();
    await wrapper.find('[data-zone="filters"]').trigger('drop', { dataTransfer: { getData: () => '{broken' } });
    expect(wrapper.text()).toContain('请从当前数据集的字段库拖入字段');
    expect(wrapper.emitted('change')).toBeUndefined();
  });
});
