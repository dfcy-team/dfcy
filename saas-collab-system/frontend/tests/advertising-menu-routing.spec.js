import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import router from '../src/router';
import { canAccessPath, menuItems } from '../src/router/menu';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('advertising analytics and finance menus', () => {
  const routes = [
    ['/analytics/advertising-overview', '广告总览'],
    ['/analytics/advertising-performance', '广告投放分析'],
    ['/finance/advertising-reconciliation', '广告费用对账']
  ];

  it.each(routes)('registers %s and places it in the expected module', (route, label) => {
    expect(router.resolve(route).matched.length, route).toBeGreaterThan(0);
    const parent = menuItems.find((item) => item.children?.some((child) => child.path === route));
    expect(parent?.label).toBe(route.startsWith('/analytics/') ? '经营分析' : '财务中心');
    expect(parent?.children?.find((child) => child.path === route)?.label).toBe(label);
  });

  it('reuses existing read permissions and denies unrelated viewers', () => {
    const analyticsViewer = { user_type: 'internal', permissions: ['analytics.view'] };
    const financeViewer = { user_type: 'internal', permissions: ['finance.view'] };
    expect(canAccessPath(analyticsViewer, '/analytics/advertising-overview')).toBe(true);
    expect(canAccessPath(analyticsViewer, '/finance/advertising-reconciliation')).toBe(false);
    expect(canAccessPath(financeViewer, '/finance/advertising-reconciliation')).toBe(true);
  });

  it('keeps advertising pages read-only and explicit about pending data', () => {
    const overview = read('src/views/analytics/AdvertisingOverview.vue');
    const performance = read('src/views/analytics/AdvertisingPerformance.vue');
    const reconciliation = read('src/views/finance/AdvertisingReconciliation.vue');
    [overview, performance, reconciliation].forEach((page) => {
      expect(page).toContain('尚未接入');
      expect(page).not.toMatch(/@click|submit|create|update|delete/i);
    });
  });
});
