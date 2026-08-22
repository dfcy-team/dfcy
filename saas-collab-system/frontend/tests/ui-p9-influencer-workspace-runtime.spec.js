import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';

import BdPerformance from '../src/views/influencers/BdPerformance.vue';
import { redirectLegacyInfluencerTab } from '../src/router';
import InfluencerList from '../src/views/influencers/InfluencerList.vue';
import { defaultCompletedDateRange } from '../src/views/influencers/performanceDate';

function createWorkspaceRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/influencers', component: InfluencerList, beforeEnter: redirectLegacyInfluencerTab },
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

  it('redirects legacy BD performance tabs before rendering and preserves other URL state', async () => {
    const router = createWorkspaceRouter();
    await router.push({
      path: '/influencers',
      query: { tab: 'bd-performance', owner: '7' },
      hash: '#legacy'
    });
    await router.isReady();

    expect(router.currentRoute.value.path).toBe('/influencers/bd-performance');
    expect(router.currentRoute.value.query).toEqual({ owner: '7' });
    expect(router.currentRoute.value.hash).toBe('#legacy');
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
