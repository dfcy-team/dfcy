import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { mockPermissions, mockRoles } from '../src/mock/systemAdmin';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

const expectedCodes = [
  'masterdata.view',
  'masterdata.manage',
  'integrations.config.view',
  'integrations.config.create',
  'integrations.config.update',
  'integrations.config.verify',
  'integrations.config.disable',
  'integrations.credential.rotate'
];

describe('仓储连接器角色权限登记', () => {
  it('在角色页面同时展示权限名称、说明和权限码', () => {
    const source = read('src/views/system/RolePermissionMatrix.vue');
    expect(source).toContain("permission.description || '暂无权限说明'");
    expect(source).toContain('class="permission-description"');
    expect(source).toContain('class="permission-code"');
  });

  it('登记档案识别和实际连接配置的独立权限边界', () => {
    const permissions = mockPermissions().data.results;
    const byCode = new Map(permissions.map((item) => [item.code, item]));

    for (const code of expectedCodes) {
      expect(byCode.has(code), code).toBe(true);
      expect(byCode.get(code).description.length, code).toBeGreaterThan(20);
    }

    expect(byCode.get('masterdata.view').description).toContain('连接器识别结果');
    expect(byCode.get('masterdata.manage').description).toContain('不授予实际连接器配置或凭据轮换');
    expect(byCode.get('integrations.config.view').name).toContain('API/WMS');
    expect(byCode.get('integrations.credential.rotate').description).toContain('不读取、导出原始凭据');
  });

  it('仅由内置管理员 mock 角色默认持有完整登记', () => {
    const roles = mockRoles().data.results;
    const administrator = roles.find((role) => role.code === 'administrator');
    const ordinary = roles.find((role) => role.code !== 'administrator');

    expect(administrator).toBeTruthy();
    expect(administrator.data_scopes).toEqual([{ scope_type: 'all', config: {} }]);
    for (const code of expectedCodes) expect(administrator.permission_codes).toContain(code);
    for (const code of expectedCodes) expect(ordinary.permission_codes).not.toContain(code);
  });
});
