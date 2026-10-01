import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  adminPermissionLabel, adminPermissionTypeLabel, adminPermissionSourceLabel,
  adminStatusLabel, adminReasonLabel, adminDimensionLabel,
} from '../src/utils/adminDisplayLabels';

const manifest = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/apps/permissions/permission_manifest.json'), 'utf8'));
const hasLatin = (value) => /[A-Za-z]/u.test(String(value || ''));

describe('管理员权限目录显示标签', () => {
  it('为权限目录全部编码显示有资源语义的中文名称', () => {
    expect(manifest.permissions).toHaveLength(400);
    const labels = manifest.permissions.map(({ code }) => [code, adminPermissionLabel(code)]);
    for (const [code, label] of labels) {
      expect(label, code).toMatch(/[\u4e00-\u9fff]/u);
      expect(hasLatin(label), code).toBe(false);
      expect(label, code).not.toMatch(/^(配置权限|查看权限)$/u);
    }
    expect(adminPermissionLabel('field.employee_readonly.product_details.sku_code.view')).toBe('查看商品明细商品编码字段');
    expect(adminPermissionLabel('field.employee_readonly.stores.platform_site_id.view')).toBe('查看店铺站点编号字段');
    expect(adminPermissionLabel('field.system.users.full_name.view')).toBe('查看用户姓名字段');
  });

  it('提供权限类型、来源、状态、原因和数据范围的中文公共标签', () => {
    expect(adminPermissionTypeLabel('field')).toBe('字段权限');
    expect(adminPermissionSourceLabel('role')).toBe('角色继承');
    expect(adminStatusLabel('active')).toBe('启用');
    expect(adminReasonLabel('')).toBe('原因未说明');
    expect(adminDimensionLabel('department')).toBe('部门');
    expect(adminStatusLabel('new-status')).toBe('其他状态');
  });
});
