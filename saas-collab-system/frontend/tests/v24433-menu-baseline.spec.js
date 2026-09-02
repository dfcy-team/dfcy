import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { flattenMenuItems, menuItems } from '../src/router/menu';

describe('current deployment menu baseline', () => {
  it('keeps the deployed top-level structure while exposing the added supply-chain and multi-platform workspaces', () => {
    expect(menuItems.map((item) => item.label)).toEqual([
      '工作台', '产品开发', '供应链协同', '多平台刊登', '经营分析', '经营决策', '销售管理', '达人管理',
      '流程协同', 'RPA协同', 'API数据接入', '财务中心', '报表中心', '基础档案',
      '系统治理', '治理与试点'
    ]);

    const development = menuItems.find((item) => item.label === '产品开发');
    expect(development.children.map((item) => item.label)).toEqual([
      '新品市调', '选品提报', '需求审核', '开发项目', '开发产品档案', '成本核算', '销售数据', '选品复盘', '效能看板'
    ]);

    const supplyChain = menuItems.find((item) => item.label === '供应链协同');
    expect(supplyChain.children.map((item) => item.label)).toEqual([
      '集货管理', '发运管理', '采购订单', '供应商绩效'
    ]);

    const sales = menuItems.find((item) => item.label === '销售管理');
    expect(sales.children.at(-1)).toMatchObject({ path: '/pricing/prices', label: '价格中心', internal: true });

    const influencers = menuItems.find((item) => item.label === '达人管理');
    expect(influencers.children.map((item) => item.label)).toEqual([
      '达人档案', '建联任务', '送样履约', 'BD绩效'
    ]);

    const governance = menuItems.find((item) => item.label === '系统治理');
    expect(governance.children.map((item) => item.label)).toEqual([
      '组织架构', '用户目录', '角色权限', '安全运维', '配置中心', '配置版本', '平台准入', '发布合同', '日志审计'
    ]);
    expect(flattenMenuItems(menuItems)).toHaveLength(109);
  });

  it('keeps moved entries unique and removes the retired business-collaboration group', () => {
    const uniquePaths = [
      '/products/research',
      '/purchasing/orders',
      '/suppliers/performance',
      '/pricing/prices',
      '/products/master',
      '/products/details',
      '/products/platform-details',
      '/listings/sites'
    ];
    const leaves = flattenMenuItems(menuItems);
    const paths = leaves.map((item) => item.path);

    expect(menuItems.some((item) => item.label === '业务协同')).toBe(false);
    for (const path of uniquePaths) {
      expect(paths.filter((itemPath) => itemPath === path), path).toHaveLength(1);
    }
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
