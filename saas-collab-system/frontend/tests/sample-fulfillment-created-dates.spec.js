import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';

const { fetchSampleFulfillments } = vi.hoisted(() => ({ fetchSampleFulfillments: vi.fn() }));
vi.mock('../src/api/influencers', async (importOriginal) => ({
  ...(await importOriginal()), fetchSampleFulfillments
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => false }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, params: {} }), useRouter: () => ({ push: vi.fn() }) }));

import SampleFulfillmentList from '../src/views/influencers/SampleFulfillmentList.vue';

const DatePicker = defineComponent({
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', { 'aria-label': props.placeholder, value: props.modelValue, onInput: (event) => emit('update:modelValue', event.target.value) });
  }
});
const Button = defineComponent({
  props: ['type'],
  emits: ['click'],
  setup(_, { slots, emit }) { return () => h('button', { onClick: (event) => { event.stopPropagation(); emit('click', event); } }, slots.default?.()); }
});

describe('sample fulfillment created date filters', () => {
  beforeEach(() => fetchSampleFulfillments.mockReset().mockResolvedValue({ success: true, data: { results: [], count: 0 } }));

  it('sends optional inclusive-calendar-date filters, keeps other filters, and clears them on reset', async () => {
    const wrapper = mount(SampleFulfillmentList, {
      global: {
        stubs: {
          'el-date-picker': DatePicker, 'el-button': Button,
          'el-input': true, 'el-select': true, 'el-option': true, 'el-checkbox': true,
          'el-card': { template: '<div><slot /></div>' }, 'el-table': true, 'el-table-column': true, 'el-pagination': true,
          'el-dialog': true, 'el-form': true, 'el-form-item': true, 'el-input-number': true,
          'el-alert': true, 'el-tag': true, 'el-drawer': true
        }
      }
    });
    await Promise.resolve();
    expect(wrapper.find('[aria-label="创建日期起"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="创建日期止"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('UTC+8');

    await wrapper.get('[aria-label="创建日期起"]').setValue('2026-11-01');
    await wrapper.get('[aria-label="创建日期止"]').setValue('2026-11-06');
    await wrapper.get('.toolbar-actions button').trigger('click');
    await Promise.resolve();
    expect(fetchSampleFulfillments).toHaveBeenLastCalledWith(expect.objectContaining({
      page: 1, created_date_from: '2026-11-01', created_date_to: '2026-11-06', ordering: '-created_at'
    }));

    wrapper.vm.page = 3;
    await wrapper.vm.$nextTick();
    await wrapper.get('[aria-label="创建日期起"]').setValue('');
    await wrapper.get('.toolbar-actions button').trigger('click');
    await Promise.resolve();
    expect(fetchSampleFulfillments).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, created_date_to: '2026-11-06' }));
    expect(fetchSampleFulfillments.mock.calls.at(-1)[0]).not.toHaveProperty('created_date_from');

    await wrapper.findAll('.toolbar-actions button')[1].trigger('click');
    await Promise.resolve();
    const resetParams = fetchSampleFulfillments.mock.calls.at(-1)[0];
    expect(resetParams).not.toHaveProperty('created_date_from');
    expect(resetParams).not.toHaveProperty('created_date_to');
    wrapper.unmount();
  });
});
