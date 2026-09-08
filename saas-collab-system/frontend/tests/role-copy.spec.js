import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('角色复制闭环', () => {
  it('通过租户隔离的复制接口提交名称和系统标识', () => {
    const api = read('src/api/systemAdmin.js');
    expect(api).toContain("url: `/api/internal/system/roles/${id}/copy/`");
    expect(api).toContain("'system.roles.copy'");
    expect(api).toContain("role_type: 'custom'");
  });

  it('操作列按角色管理权限显示复制并遵循禁用原因', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('>复制</el-button>');
    expect(page).toContain('v-if="manageAccess.visible"');
    expect(page).toContain(':disabled="manageAccess.disabled"');
    expect(page).toContain(':title="manageAccess.reason"');
    expect(page).toContain('@click="openCopyRole(row)"');
  });

  it('复制对话框展示来源并在成功后打开新角色权限配置', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    for (const phrase of [
      '复制为自定义角色',
      '来源角色：',
      '角色名称',
      '系统标识',
      '复制并配置',
      '系统会原样复制来源角色当前的权限和数据范围',
      '@closed="finishCopyRole"',
      'pendingCopiedRole',
      'await load();',
      'if (copiedRole?.id) openRole(copiedRole);',
    ]) expect(page).toContain(phrase);
    expect(page).toContain('copyRoleForm');
    expect(page).toContain('copySourceRole');
  });

  it('为重复复制生成递增系统标识，最终仍由后端校验唯一性', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain("index === 1 ? '-copy' : `-copy-${index}`");
    expect(page).toContain('if (!existingCodes.has(candidate)) return candidate');
    expect(page).toContain('系统标识（不可修改）');
  });
});
