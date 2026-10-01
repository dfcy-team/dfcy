import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessPath, filterMenuItems, flattenMenuItems, menuItems, pendingReportPaths, routeCapabilities } from '../src/router/menu';
import { buildInventoryCostLocation, historicalDateLabel } from '../src/views/analytics/InventoryAnalysis.vue';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('report navigation revision', () => {
  it('keeps each report entry in its authorized business module', () => {
    const expected = {
      '/analytics/overview': '经营分析', '/analytics/sales': '经营分析', '/analytics/inventory': '经营分析',
      '/sales-management/overview': '销售管理', '/sales-management/orders': '销售管理', '/sales-management/returns': '销售管理',
      '/inventory/workbench': '库存管理', '/decision/inventory/alerts': '库存管理', '/decision/inventory/replenishment': '库存管理',
      '/finance/analytics': '财务中心', '/finance/statements': '财务中心',
      '/reports/basic': '报表中心', '/reports/exports': '报表中心', '/products/costs': '基础档案'
    };
    for (const [path, module] of Object.entries(expected)) {
      const owners=menuItems.filter(item=>flattenMenuItems(item.children||[]).some(child=>child.path===path));
      expect(owners.map(item=>item.label)).toEqual([module]);
    }
  });

  it('keeps planned advertising routes declared, accessible, and visible in their authorized menus', () => {
    const user = { user_type: 'internal', permissions: ['analytics.view', 'finance.view'] };
    expect(pendingReportPaths).toEqual([
      '/analytics/advertising-overview',
      '/analytics/advertising-performance',
      '/finance/advertising-reconciliation'
    ]);
    for (const path of pendingReportPaths) {
      expect(flattenMenuItems(menuItems).some(item => item.path === path)).toBe(true);
      expect(routeCapabilities.some(item => item.path === path)).toBe(true);
      expect(canAccessPath(user, path)).toBe(true);
      expect(flattenMenuItems(filterMenuItems(user)).some(item => item.path === path)).toBe(true);
    }
  });

  it('keeps planned advertising entries subject to viewer grants and disabled modules', () => {
    const visible = (user) => flattenMenuItems(filterMenuItems(user)).filter(item => pendingReportPaths.includes(item.path)).map(item => item.path);
    const analytics = { user_type: 'internal', permissions: ['analytics.view'] };
    const finance = { user_type: 'internal', permissions: ['finance.view'] };
    expect(visible(analytics)).toEqual(pendingReportPaths.slice(0, 2));
    expect(visible(finance)).toEqual([pendingReportPaths[2]]);
    expect(visible({ user_type: 'internal', permissions: [] })).toEqual([]);
    expect(visible({ ...analytics, module_statuses: { analytics: 'disabled' } })).toEqual([]);
    expect(visible({ ...finance, module_statuses: { finance: 'disabled' } })).toEqual([]);
  });

  it('preserves report filter navigation and explicit, permission-gated order drillthrough', () => {
    const sales = read('src/views/sales-management/SalesWorkspace.vue');
    expect(sales).toContain('canAccessPath(auth.currentUser, tab.path)');
    expect(sales).toContain('watch(() => route.query');
    expect(sales).toContain('function drillToOrders(row)');
    expect(sales).toContain("params.include_summary = 'false'");
  });

  it('opens a historical inventory snapshot and links mapped rows to the correct cost version', () => {
    const inventory = read('src/views/analytics/InventoryAnalysis.vue');
    expect(inventory).toContain("ref(route?.query?.include_virtual === 'true')");
    expect(inventory).toContain('@row-click="openInventoryRow"');
    expect(inventory).toContain('title="库存历史快照"');
    expect(inventory).toContain("canAccessPath(auth.currentUser, '/products/costs')");
    expect(inventory).not.toContain("path: '/analytics/sales'");
    expect(historicalDateLabel({ date_range: ['2026-08-01', '2026-08-31'] })).toBe('2026-08-01 至 2026-08-31');
    expect(buildInventoryCostLocation({ internal_sku_id: 19, warehouse_id: 8, snapshot_time: '2026-08-31T23:59:00Z' })).toEqual({
      query: { sku_id: 19, warehouse_id: 8, occurred_at: '2026-08-31T23:59:00Z' }
    });
    expect(buildInventoryCostLocation({ internal_sku_id: 19 })).toEqual({ query: { sku_id: 19 } });
  });
});
