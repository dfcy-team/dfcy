import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('product development workflow contract', () => {
  it('exposes exactly the reviewed eleven workflow menu entries', () => {
    const menu = read('src/router/menu.js');
    const labels = ['候选款登记', '竞品监控', '样品/打样管理', '比价管理', '成本核算', '上架决策', '开发档案/转正', '首单与试销', '返单决策', '淘汰库', '开发设置'];
    labels.forEach((label) => expect(menu).toContain(`label: '${label}'`));
    expect(menu).not.toContain("label: '需求审核'");
  });

  it('keeps legacy links routable while redirecting them to the new workflow', () => {
    const router = read('src/router/index.js');
    expect(router).toContain("{ path: 'development/requirements', redirect: '/development/candidates' }");
    expect(router).toContain("{ path: 'development/review', redirect: '/development/candidates' }");
    expect(router).toContain("{ path: 'development/projects', redirect: '/development/candidates' }");
    expect(router).toContain("{ path: 'development/sales', redirect: '/development/trials' }");
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
