import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { filterMenuItems, flattenMenuItems, menuItems } from '../src/router/menu';

describe('current deployment menu baseline', () => {
  it('keeps the approved top-level order and exposes the reorganized workspaces', () => {
    expect(menuItems.map((item) => item.label)).toEqual([
      '工作台', '基础档案', '产品开发', '供应链协同', '库存管理', '全球刊登', '销售管理', '达人管理',
      '财务中心', '经营分析', '经营决策', '报表中心', '流程协同', 'RPA协同', 'API数据接入', '系统管理',
      '治理与试点'
    ]);

    const inventory = menuItems.find((item) => item.label === '库存管理');
    expect(inventory).toMatchObject({ internal: true, permissions: ['alerts.view', 'replenishment.view'] });
    expect(inventory.children.map((item) => item.label)).toEqual(['库存预警', '补货建议']);

    const development = menuItems.find((item) => item.label === '产品开发');
    expect(development.children.map((item) => item.label)).toEqual([
      '新品市调', '选品提报', '需求审核', '开发项目', '开发产品档案', '成本核算', '销售数据', '选品复盘', '效能看板'
    ]);

    const supplyChain = menuItems.find((item) => item.label === '供应链协同');
    expect(supplyChain.children.map((item) => item.label)).toEqual(['集货管理', '发运管理', '采购订单', '供应商绩效']);

    const listings = menuItems.find((item) => item.label === '全球刊登');
    expect(listings.children.map((item) => item.label)).toEqual([
      '全球刊登工作台', '刊登任务', '在线商品', '平台类目映射', '商品属性映射', '刊登日志', '刊登异常', '刊登资料', '刊登模板'
    ]);

    const sales = menuItems.find((item) => item.label === '销售管理');
    expect(sales).toMatchObject({ internal: true, showWhenChildAccessible: true });
    expect(sales.permissions).toEqual(expect.arrayContaining([
      'sales_management.view', 'sales_management.orders.view', 'sales_management.returns.view',
      'sales_management.stores.view', 'sales_management.skus.view', 'sales_management.export',
      'sales_management.data_quality.view', 'sales_management.sync.view'
    ]));
    expect(sales.children.at(-1)).toMatchObject({ path: '/pricing/prices', label: '价格中心', internal: true });

    const api = menuItems.find((item) => item.label === 'API数据接入');
    expect(api.permissions).toEqual(expect.arrayContaining([
      'integrations.view', 'integrations.store.view', 'integrations.audit.view', 'integrations.config.view',
      'config.system.manage', 'masterdata.view'
    ]));
    expect(api.children.map((item) => item.path)).toEqual(expect.arrayContaining([
      '/master-data/platforms', '/integrations/platform-sites', '/master-data/stores',
      '/integrations/production-settings', '/integrations/configs', '/integrations/sync-runs'
    ]));

    const system = menuItems.find((item) => item.label === '系统管理');
    expect(system).toBeTruthy();
    expect(menuItems.some((item) => item.label === '系统治理')).toBe(false);
    expect(menuItems.some((item) => item.label === '业务协同')).toBe(false);
    expect(flattenMenuItems(menuItems)).toHaveLength(113);
  });

  it('keeps migrated and global-listing routes in one menu with the API entries routable', () => {
    const flatItems = flattenMenuItems(menuItems);
    const parentFor = (route) => menuItems.find((item) => item.children?.some((child) => child.path === route))?.label;
    const migratedParents = {
      '/products/research': '产品开发',
      '/purchasing/orders': '供应链协同',
      '/suppliers/performance': '供应链协同',
      '/pricing/prices': '销售管理'
    };
    for (const [route, parent] of Object.entries(migratedParents)) {
      expect(flatItems.filter((item) => item.path === route), route).toHaveLength(1);
      expect(parentFor(route), route).toBe(parent);
    }
    for (const route of [
      '/listings/workbench', '/listings/tasks', '/listings/online-products', '/listings/category-mappings',
      '/listings/attribute-mappings', '/listings/logs', '/listings/exceptions', '/listings/sites', '/listings/templates',
      '/integrations/production-settings'
    ]) {
      expect(flatItems.filter((item) => item.path === route), route).toHaveLength(1);
    }
  });

  it('keeps the internal price-center entry visible without sales permissions', () => {
    const internalPriceOnly = { user_type: 'internal', is_superuser: false, permissions: [] };
    const internalPaths = flattenMenuItems(filterMenuItems(internalPriceOnly)).map((item) => item.path);
    expect(internalPaths).toContain('/pricing/prices');
    expect(internalPaths).not.toContain('/sales-management/overview');

    const externalPaths = flattenMenuItems(filterMenuItems({
      user_type: 'external', is_superuser: false, permissions: []
    })).map((item) => item.path);
    expect(externalPaths).not.toContain('/pricing/prices');
  });

  it('keeps the current dark desktop and mobile navigation palette', () => {
    const layout = fs.readFileSync(path.resolve(process.cwd(), 'src/layouts/MainLayout.vue'), 'utf8');
    for (const color of ['#101827', '#0b1220', '#1e293b', '#1d4ed8', '#1e40af', '#cbd5e1', '#f8fafc']) {
      expect(layout).toContain(color);
    }
    expect(layout).toContain('class="navigation-surface"');
    expect(layout).toContain('class="navigation-drawer"');
    expect(layout).toContain(':global(.navigation-drawer .el-drawer__body)');
  });
});
