import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import router from '../src/router';
import { canAccessPath, filterMenuItems, flattenMenuItems, menuItems, routeCapabilities } from '../src/router/menu';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

const salesRoutes = [
  '/sales-management/overview',
  '/sales-management/orders',
  '/sales-management/returns',
  '/sales-management/stores',
  '/sales-management/skus',
  '/sales-management/exports',
  '/sales-management/data-quality'
];

const salesPermissions = [
  'sales_management.view',
  'sales_management.orders.view',
  'sales_management.returns.view',
  'sales_management.stores.view',
  'sales_management.skus.view',
  'sales_management.export',
  'sales_management.data_quality.view',
  'sales_management.sync.view'
];

describe('sales management routing contract', () => {
  it('registers all seven routes under the dedicated namespace', () => {
    for (const path of salesRoutes) {
      expect(router.resolve(path).matched.length, path).toBeGreaterThan(0);
      expect(routeCapabilities.find((item) => item.path === path), path).toBeTruthy();
    }
    expect(read('src/router/index.js')).not.toContain("path: 'analytics/sales', component: SalesOverview");
  });

  it('adds one top-level menu between经营决策 and达人管理 without changing the existing order', () => {
    const labels = menuItems.map((item) => item.label);
    expect(labels.indexOf('经营决策')).toBeGreaterThanOrEqual(0);
    expect(labels.indexOf('销售管理')).toBe(labels.indexOf('经营决策') + 1);
    expect(labels.indexOf('达人管理')).toBe(labels.indexOf('销售管理') + 1);
    expect(labels.indexOf('流程协同')).toBe(labels.indexOf('达人管理') + 1);
    const salesMenu = menuItems.find((item) => item.label === '销售管理');
    expect(salesMenu.children.map((item) => item.path)).toEqual(salesRoutes);
    expect([...new Set(salesMenu.permissions)].sort()).toEqual([...salesPermissions].sort());
  });

  it('filters each sales route by its exact internal permission and denies external users', () => {
    const viewer = { user_type: 'internal', permissions: ['sales_management.orders.view'] };
    const paths = flattenMenuItems(filterMenuItems(viewer)).map((item) => item.path);
    expect(paths.filter((path) => path.startsWith('/sales-management/'))).toEqual(['/sales-management/orders']);
    expect(canAccessPath(viewer, '/sales-management/orders')).toBe(true);
    expect(canAccessPath(viewer, '/sales-management/returns')).toBe(false);
    expect(canAccessPath({ ...viewer, user_type: 'external' }, '/sales-management/orders')).toBe(false);
  });
});
