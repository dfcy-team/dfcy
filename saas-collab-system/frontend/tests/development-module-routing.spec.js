import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('product development workflow contract', () => {
  it('preserves the V2.44.33 development menu entries', () => {
    const menu = read('src/router/menu.js');
    const labels = ['选品提报', '需求审核', '开发项目', '开发产品档案', '成本核算', '销售数据', '选品复盘', '效能看板'];
    labels.forEach((label) => expect(menu).toContain(`label: '${label}'`));
    expect(menu).not.toContain("label: '候选款登记'");
  });

  it('keeps the V2.44.33 development routes directly routable', () => {
    const router = read('src/router/index.js');
    expect(router).toContain("{ path: 'development/requirements', component: DevelopmentWorkspace, props: { mode: 'requirements' } }");
    expect(router).toContain("{ path: 'development/review', component: DevelopmentWorkspace, props: { mode: 'review' } }");
    expect(router).toContain("{ path: 'development/projects', component: DevelopmentWorkspace, props: { mode: 'projects' } }");
    expect(router).toContain("{ path: 'development/sales', component: DevelopmentWorkspace, props: { mode: 'sales' } }");
  });

  it('provides the candidate conditional fields and keeps review out of the early form', () => {
    const page = read('src/views/development/DevelopmentWorkspace.vue');
    expect(page).toContain('development_type');
    expect(page).toContain('trial_mode');
    expect(page).toContain('original_model');
    expect(page).toContain('design_files');
    expect(page).toContain('design_sent_date');
    expect(page).toContain('商品分类（允许 L2/L3）');
    expect(page).toContain('不设置独立强制需求审核');
    expect(page).toContain('请选择 L2 或 L3 分类');
  });

  it('documents both trial exits and exposes the complete development API resource set', () => {
    const page = read('src/views/development/DevelopmentWorkspace.vue');
    const api = read('src/api/development.js');
    expect(page).toContain('实际小单测款达标可直接转正');
    expect(page).toContain('虚拟库存测款达标后先进入上新计划');
    ['candidates', 'projects', 'samples', 'quotations', 'listing-decisions', 'trials', 'trial-metrics', 'launch-plans', 'reorder-decisions', 'eliminations', 'events', 'settings'].forEach((resource) => {
      expect(api).toContain(`resourceApi('${resource}')`);
    });
  });
});
