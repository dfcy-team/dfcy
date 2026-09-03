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

  it('keeps the approved top-level order after removing业务协同', () => {
    const labels = menuItems.map((item) => item.label);
    expect(labels).toEqual([
      '工作台', '基础档案', '产品开发', '供应链协同', '库存管理', '全球刊登', '销售管理', '达人管理',
      '财务中心', '经营分析', '经营决策', '报表中心', '流程协同', 'RPA协同', 'API数据接入', '系统管理', '治理与试点'
    ]);
    expect(labels).not.toContain('业务协同');
    expect(labels.indexOf('销售管理')).toBe(labels.indexOf('全球刊登') + 1);
    expect(labels.indexOf('达人管理')).toBe(labels.indexOf('销售管理') + 1);
    const salesMenu = menuItems.find((item) => item.label === '销售管理');
    expect(salesMenu.internal).toBe(true);
    expect(salesMenu.showWhenChildAccessible).toBe(true);
    expect(salesMenu.children.map((item) => item.path)).toEqual([...salesRoutes, '/pricing/prices']);
    expect([...new Set(salesMenu.permissions)].sort()).toEqual([...salesPermissions].sort());
    expect(salesMenu.children.at(-1)).toMatchObject({ label: '价格中心', internal: true });
  });

  it('filters each sales route by its exact internal permission and denies external users', () => {
    const viewer = { user_type: 'internal', permissions: ['sales_management.orders.view'] };
    const paths = flattenMenuItems(filterMenuItems(viewer)).map((item) => item.path);
    expect(paths.filter((path) => path.startsWith('/sales-management/'))).toEqual(['/sales-management/orders']);
    expect(paths).toContain('/pricing/prices');
    expect(canAccessPath(viewer, '/sales-management/orders')).toBe(true);
    expect(canAccessPath(viewer, '/sales-management/returns')).toBe(false);
    expect(canAccessPath({ ...viewer, user_type: 'external' }, '/sales-management/orders')).toBe(false);
  });

  it('shows the internal price center without sales permission and hides it externally', () => {
    const internalPaths = flattenMenuItems(filterMenuItems({ user_type: 'internal', permissions: [] }))
      .map((item) => item.path);
    expect(internalPaths).toContain('/pricing/prices');
    expect(internalPaths).not.toContain('/sales-management/overview');

    const externalPaths = flattenMenuItems(filterMenuItems({ user_type: 'external', permissions: [] }))
      .map((item) => item.path);
    expect(externalPaths).not.toContain('/pricing/prices');
  });

  it('shows each moved entry through its owning parent and keeps internal-only pricing hidden externally', () => {
    const visibleChildren = (user, parentLabel) => {
      const parent = filterMenuItems(user).find((item) => item.label === parentLabel);
      return parent?.children.map((item) => item.path) || [];
    };

    expect(visibleChildren({ user_type: 'internal', permissions: ['products.research.view'] }, '产品开发'))
      .toContain('/products/research');
    expect(visibleChildren({ user_type: 'internal', permissions: ['purchasing.orders.view'] }, '供应链协同'))
      .toContain('/purchasing/orders');
    expect(visibleChildren({ user_type: 'internal', permissions: ['suppliers.performance.view'] }, '供应链协同'))
      .toContain('/suppliers/performance');

    const internalWithoutSalesPermission = { user_type: 'internal', permissions: [] };
    expect(visibleChildren(internalWithoutSalesPermission, '销售管理')).toContain('/pricing/prices');
    expect(visibleChildren({ user_type: 'external', permissions: [] }, '销售管理')).toEqual([]);
  });
});
