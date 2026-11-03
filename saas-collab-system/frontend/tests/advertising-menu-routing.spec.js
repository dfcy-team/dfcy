import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import router from '../src/router';
import { canAccessPath, filterSidebarMenuItems, menuItems } from '../src/router/menu';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const findItem = (items, route) => {
  for (const item of items) {
    if (item.path === route) return item;
    const nested = item.children && findItem(item.children, route);
    if (nested) return nested;
  }
  return null;
};

describe('advertising analytics and finance menus', () => {
  const routes = [
    ['/marketing/advertising/shopee/overview', '广告总览'],
    ['/marketing/advertising/shopee/performance', '广告投放分析'],
    ['/marketing/advertising/tiktok/overview', '广告总览'],
    ['/marketing/advertising/tiktok/performance', '广告投放分析'],
    ['/finance/advertising-reconciliation', '广告费用对账']
  ];

  it.each(routes)('registers %s and places it in the expected module', (route, label) => {
    expect(router.resolve(route).matched.length, route).toBeGreaterThan(0);
    const item = findItem(menuItems, route);
    expect(item?.label).toBe(label);
    if (route.startsWith('/marketing/')) expect(findItem(menuItems, route)).toBeTruthy();
  });

  it('reuses existing read permissions and denies unrelated viewers', () => {
    const analyticsViewer = { user_type: 'internal', permissions: ['analytics.view'] };
    const financeViewer = { user_type: 'internal', permissions: ['finance.view'] };
    expect(canAccessPath(analyticsViewer, '/analytics/advertising-overview')).toBe(true);
    expect(canAccessPath({ ...analyticsViewer, module_statuses: { analytics: 'disabled' } }, '/analytics/advertising-overview')).toBe(false);
    expect(canAccessPath({ ...analyticsViewer, module_statuses: { marketing: 'disabled' } }, '/analytics/advertising-overview')).toBe(true);
    expect(findItem(filterSidebarMenuItems(analyticsViewer), '/analytics/advertising-overview')?.label).toBe('广告分析');
    expect(canAccessPath(analyticsViewer, '/finance/advertising-reconciliation')).toBe(false);
    expect(canAccessPath(financeViewer, '/finance/advertising-reconciliation')).toBe(true);
  });

  it('queries persisted Shopee reports while keeping reconciliation pending', () => {
    const overview = read('src/views/analytics/AdvertisingOverview.vue');
    const performance = read('src/views/analytics/AdvertisingPerformance.vue');
    const reconciliation = read('src/views/finance/AdvertisingReconciliation.vue');
    expect(performance).toContain('ShopeeAdvertisingReport');
    expect(reconciliation).toContain('AdvertisingReportPlaceholder');
    expect(reconciliation).toContain('advertisingReportPlans');
    const api = read('src/api/advertising.js');
    expect(api).toContain('/internal/analytics/advertising/');
    expect(api).not.toContain('requestWithMockFallback');
    expect(overview).toContain('国家／平台对比');
    expect(overview).toContain('你没有查看基础报表的权限');
    expect(overview).not.toContain('ShopeeAdvertisingReport');
    const placeholder = read('src/components/AdvertisingReportPlaceholder.vue');
    expect(placeholder).toContain('<h1>{{ plan.title }}</h1>');
    expect(placeholder).toContain('待接入');
    expect(placeholder).toContain('— / 未采集');
    ['报表规划', '指标口径', '接入条件'].forEach((label) => expect(placeholder).toContain(label));
  });

  it('keeps legacy advertising URLs and finance menu unchanged, with platform locked on new report entries', () => {
    ['/analytics/advertising-overview', '/analytics/advertising-performance'].forEach((route) => {
      expect(router.resolve(route).matched.length, route).toBeGreaterThan(0);
      expect(canAccessPath({ user_type: 'internal', permissions: ['analytics.view'], module_statuses: { marketing: 'disabled', analytics: 'enabled' } }, route)).toBe(route === '/analytics/advertising-overview');
    });
    const finance = menuItems.find((item) => item.label === '财务中心');
    expect(finance?.children?.find((item) => item.path === '/finance/advertising-reconciliation')?.label).toBe('广告费用对账');
    const marketing = menuItems.find((item) => item.label === '营销管理');
    expect(marketing?.children?.find((item) => item.label === '平台活动')?.children).toBeUndefined();
    expect(read('src/components/ShopeeAdvertisingReport.vue')).toContain("...(props.fixedPlatform ? { platform: props.fixedPlatform } : {})");
    expect(read('src/router/index.js')).toContain("props: { platform: 'tiktok', performance: true }");
    const viewer = { user_type: 'internal', permissions: ['analytics.view'] };
    for (const route of ['/marketing/campaigns', '/marketing/advertising/shopee/overview', '/marketing/advertising/tiktok/performance']) {
      expect(canAccessPath(viewer, route)).toBe(true);
      expect(canAccessPath({ user_type: 'internal', permissions: [] }, route)).toBe(false);
      expect(canAccessPath({ user_type: 'internal', permissions: ['analytics.view'], module_statuses: { marketing: 'disabled' } }, route)).toBe(false);
    }
    const visibleMarketing = filterSidebarMenuItems(viewer).find((item) => item.label === '营销管理');
    expect(findItem([visibleMarketing], '/marketing/advertising/tiktok/performance')?.label).toBe('广告投放分析');
    expect(read('src/components/TikTokAdsDailySpendOverview.vue')).toContain('fetchTikTokDailySpend');
    expect(read('src/api/advertising.js')).toContain('/tiktok-daily-spend/');
  });
});
