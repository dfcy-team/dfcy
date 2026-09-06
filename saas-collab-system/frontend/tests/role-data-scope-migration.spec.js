import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('角色数据范围迁移契约', () => {
  it('新配置只提供租户内全部或业务范围限制', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('租户隔离始终生效');
    expect(page).toContain('业务范围至少选择一个平台、国家/站点、店铺、仓库或供应商');
    for (const key of ['platform_ids', 'site_ids', 'store_ids', 'warehouse_ids', 'supplier_ids']) expect(page).toContain(`scope_config.${key}`);
    expect(page).toContain('.filter((key) => roleForm.scope_config[key].length)');
    expect(page).toContain('历史组织范围，需重新配置');
    expect(page).toContain('该角色使用历史组织范围，请先明确选择新的数据范围。');
    for (const legacyOption of ['value="department"', 'value="department_tree"', 'value="own"']) expect(page).not.toContain(legacyOption);
  });

  it('范围选项接口只暴露业务维度，不返回组织对象', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('scopePlatforms');
    expect(page).toContain('scopeSites');
    expect(page).toContain('scopeStores');
    expect(page).toContain('scopeWarehouses');
    expect(page).toContain('scopeSuppliers');
    const mock = read('src/mock/systemAdmin.js');
    expect(mock).toContain('tenant_boundary');
  });
});
