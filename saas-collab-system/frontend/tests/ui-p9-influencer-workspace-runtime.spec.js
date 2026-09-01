import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';

import BdPerformance from '../src/views/influencers/BdPerformance.vue';
import InfluencerList from '../src/views/influencers/InfluencerList.vue';
import { bdPerformanceErrorMessage, calendarDayCount, defaultCompletedDateRange, isDateRangeWithinLimit } from '../src/views/influencers/performanceDate';

function createWorkspaceRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/influencers', component: InfluencerList },
      { path: '/influencers/bd-performance', component: BdPerformance }
    ]
  });
}

const stubs = {
  InfluencerResourceLibrary: { template: '<div data-test="library-panel">资源库</div>' },
  BdPerformancePanel: { template: '<div data-test="performance-panel">绩效</div>' }
};

describe('influencer workspace runtime behavior', () => {
  it('uses local calendar days for the last seven completed days', () => {
    const now = new Date(2026, 7, 17, 0, 30, 0);
    expect(defaultCompletedDateRange(now)).toEqual({ startDay: '2026-08-10', endDay: '2026-08-16' });
  });

  it('enforces the BD performance inclusive 31-day reporting limit', () => {
    expect(calendarDayCount('2026-07-01', '2026-07-31')).toBe(31);
    expect(calendarDayCount('2026-07-01', '2026-08-01')).toBe(32);
    expect(calendarDayCount('2028-02-01', '2028-03-02')).toBe(31);
    expect(isDateRangeWithinLimit('2026-07-01', '2026-07-31')).toBe(true);
    expect(isDateRangeWithinLimit('2026-07-01', '2026-08-01')).toBe(false);
    expect(isDateRangeWithinLimit('2026-08-01', '2026-07-31')).toBe(false);
  });

  it('translates BD performance date validation errors for the workspace', () => {
    expect(bdPerformanceErrorMessage({ message: 'The date range must not exceed 31 days.' })).toContain('31 个自然日');
    expect(bdPerformanceErrorMessage({ message: 'end_date must not exceed yesterday or the imported order date.' })).toBe('结束日期不能晚于昨日或当前已导入订单日期，请重新选择');
    expect(bdPerformanceErrorMessage({ message: 'temporary failure' })).toBe('temporary failure');
  });

  it('keeps BD performance on its independent route and preserves URL state', async () => {
    const router = createWorkspaceRouter();
    await router.push({
      path: '/influencers/bd-performance',
      query: { owner: '7' },
      hash: '#bd'
    });
    await router.isReady();

    expect(router.currentRoute.value.path).toBe('/influencers/bd-performance');
    expect(router.currentRoute.value.query).toEqual({ owner: '7' });
    expect(router.currentRoute.value.hash).toBe('#bd');
  });

  it('renders BD performance on its independent route with the existing panel', async () => {
    const router = createWorkspaceRouter();
    await router.push('/influencers/bd-performance');
    await router.isReady();
    const wrapper = mount(BdPerformance, { global: { plugins: [router], stubs } });

    expect(wrapper.get('h1').text()).toBe('BD 绩效');
    expect(wrapper.get('p').text()).toBe('按日期范围查看达人开拓、送样投入与合作产出。');
    expect(wrapper.find('[data-test="performance-panel"]').exists()).toBe(true);
  });
});
