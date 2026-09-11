import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const influencerApi = vi.hoisted(() => ({
  BD_PERFORMANCE_CURRENCIES: [{ value: 'CNY', label: '人民币 CNY' }],
  fetchBdPerformance: vi.fn(),
  formatInfluencerError: vi.fn((response, fallback) => response?.data?.end_date?.[0] || response?.message || fallback)
}));

vi.mock('../src/api/influencers', () => influencerApi);

import BdPerformancePanel from '../src/views/influencers/BdPerformancePanel.vue';

const stubs = {
  'el-alert': {
    props: ['title'],
    template: '<div class="alert">{{ title }}<slot /></div>'
  },
  'el-button': {
    props: ['disabled', 'loading'],
    emits: ['click'],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>'
  },
  'el-card': { template: '<div><slot /></div>' },
  'el-date-picker': {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<input class="date-picker" :aria-label="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />'
  },
  'el-option': { template: '<option />' },
  'el-select': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>'
  },
  'el-table': { props: ['data'], template: '<div class="table"><slot /></div>' },
  'el-table-column': true
};

const successResponse = () => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: {
    start_date: '2026-08-30',
    end_date: '2026-09-05',
    currency: 'CNY',
    results: [{ owner: '李明', sample_count: 3, gmv: '100.00', roi: '2.5' }],
    totals: { owner_count: 1, sample_count: 3, gmv: '100.00', roi: '2.5' }
  }
});

const mountPanel = () => mount(BdPerformancePanel, { global: { stubs } });

describe('BD performance data-aware default range', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    influencerApi.fetchBdPerformance.mockResolvedValue(successResponse());
  });

  it('lets the backend choose the initial range, displays it, and sends edited dates on refresh', async () => {
    const wrapper = mountPanel();
    await flushPromises();

    expect(influencerApi.fetchBdPerformance).toHaveBeenNthCalledWith(1, {
      currency: 'CNY',
      attribution: 'strict',
      metrics: 'core'
    });
    expect(wrapper.text()).toContain('统计范围：2026-08-30 至 2026-09-05');

    const [startDate, endDate] = wrapper.findAll('.date-picker');
    expect(startDate.element.value).toBe('2026-08-30');
    expect(endDate.element.value).toBe('2026-09-05');
    await startDate.setValue('2026-09-01');
    await endDate.setValue('2026-09-04');
    await wrapper.findAll('button').find((button) => button.text().includes('刷新统计')).trigger('click');
    await flushPromises();

    expect(influencerApi.fetchBdPerformance).toHaveBeenNthCalledWith(2, {
      currency: 'CNY',
      attribution: 'strict',
      metrics: 'core',
      start_date: '2026-09-01',
      end_date: '2026-09-04'
    });
  });

  it('shows a field-level API validation error instead of the generic envelope message', async () => {
    influencerApi.fetchBdPerformance.mockResolvedValue({
      success: false,
      code: 'VALIDATION_ERROR',
      message: 'error message',
      data: { end_date: ['结束日期不能晚于已导入订单日期。'] },
      http_status: 400
    });

    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.find('.alert').text()).toContain('结束日期不能晚于已导入订单日期。');
    expect(wrapper.find('.alert').text()).not.toContain('error message');
    expect(influencerApi.formatInfluencerError).toHaveBeenCalled();
  });
});
