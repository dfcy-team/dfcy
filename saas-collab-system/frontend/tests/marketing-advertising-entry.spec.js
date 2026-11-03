import { shallowMount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import MarketingAdvertising from '../src/views/analytics/MarketingAdvertising.vue';
import ShopeeAdvertisingReport from '../src/components/ShopeeAdvertisingReport.vue';
import TikTokAdsDailySpendOverview from '../src/components/TikTokAdsDailySpendOverview.vue';

describe('marketing advertising platform entries', () => {
  it.each([
    ['shopee', false], ['shopee', true]
  ])('passes fixed platform and performance=%s to the Shopee report', (platform, performance) => {
    const wrapper = shallowMount(MarketingAdvertising, { props: { platform, performance } });
    const report = wrapper.findComponent(ShopeeAdvertisingReport);
    expect(report.props('fixedPlatform')).toBe('shopee');
    expect(report.props('performance')).toBe(performance);
    expect(wrapper.findComponent(TikTokAdsDailySpendOverview).exists()).toBe(false);
  });

  it.each([false, true])('passes performance=%s to TikTok stored report', (performance) => {
    const wrapper = shallowMount(MarketingAdvertising, { props: { platform: 'tiktok', performance } });
    expect(wrapper.findComponent(TikTokAdsDailySpendOverview).props('performance')).toBe(performance);
    expect(wrapper.findComponent(TikTokAdsDailySpendOverview).props('active')).toBe(true);
    expect(wrapper.findComponent(ShopeeAdvertisingReport).exists()).toBe(false);
  });
});
