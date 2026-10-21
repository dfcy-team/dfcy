import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const fetchReferences = vi.hoisted(() => vi.fn());
vi.mock('../src/api/operatingOrdersV2', () => ({ fetchOperatingReferences: fetchReferences }));

import OperatingReferenceV2 from '../src/components/supply-chain/OperatingReferenceV2.vue';

const result = (override = {}) => ({ success: true, data: {
  lines: [], candidate_count: 45, scanned_count: 20, next_offset: 20, has_more: true,
  platform_options: [], generated_at: '2026-10-21T00:00:00Z', ...override
} });
const stubs = {
  'el-select': { props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-input': { template: '<input />' },
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-table': { props: ['data', 'emptyText'], template: '<div><span v-if="!data.length">{{ emptyText }}</span><slot/></div>' },
  'el-table-column': true, 'el-checkbox': true, 'el-pagination': true,
  OperatingProductImageV2: true, DocumentSkuV2: true, OperatingDemandV2: true
};
const mountReference = () => mount(OperatingReferenceV2, { props: {
  parameters: { country_id: 2, source_kind: 'cycle' }, validate: () => true
}, global: { stubs } });

describe('operating reference quantity filter and continuation', () => {
  beforeEach(() => fetchReferences.mockReset().mockResolvedValue(result()));
  afterEach(() => vi.restoreAllMocks());

  it('defaults to positive suggestions, supports batch backtracking, and restarts a changed filter at zero', async () => {
    const wrapper = mountReference();
    await wrapper.findAll('button').find(button => button.text().includes('生成国家参考清单')).trigger('click');
    await flushPromises();
    expect(fetchReferences.mock.calls[0][0]).toMatchObject({ quantity_filter: 'positive', offset: 0, limit: 20 });

    await wrapper.findAll('button').find(button => button.text().includes('继续查找下一批')).trigger('click');
    await flushPromises();
    expect(fetchReferences.mock.calls[1][0].offset).toBe(20);
    await wrapper.findAll('button').find(button => button.text() === '上一批').trigger('click');
    await flushPromises();
    expect(fetchReferences.mock.calls[2][0].offset).toBe(0);

    await wrapper.findAll('select')[1].setValue('all');
    await flushPromises();
    expect(fetchReferences.mock.calls[3][0]).toMatchObject({ quantity_filter: 'all', offset: 0 });
    wrapper.unmount();
  });

  it('retries a failed continuation at the same offset and shows a completed empty batch', async () => {
    fetchReferences.mockResolvedValueOnce(result()).mockRejectedValueOnce(new Error('temporary'))
      .mockResolvedValueOnce(result({ scanned_count: 5, next_offset: 25, has_more: false, lines: [] }));
    const wrapper = mountReference();
    await wrapper.findAll('button').find(button => button.text().includes('生成国家参考清单')).trigger('click');
    await flushPromises();
    const next = () => wrapper.findAll('button').find(button => button.text().includes('继续查找下一批')).trigger('click');
    await next(); await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === '重试本批').trigger('click'); await flushPromises();
    expect(fetchReferences.mock.calls[1][0].offset).toBe(20);
    expect(fetchReferences.mock.calls[2][0].offset).toBe(20);
    expect(wrapper.text()).toContain('没有符合条件的商品，候选已查完');
    expect(wrapper.findAll('button').find(button => button.text().includes('继续查找下一批')).element.disabled).toBe(true);
    wrapper.unmount();
  });
});
