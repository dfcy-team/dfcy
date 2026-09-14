import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { roleSaveErrorMessage, selectedPermissionCount } from '../src/utils/rolePermissionFeedback';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('角色权限配置反馈', () => {
  it('按菜单分组统计已勾选数量', () => {
    const menu = {
      children: [
        { permissions: [{ code: 'menu.products.view' }, { code: 'menu.products.details.view' }] },
        { permissions: [{ code: 'menu.masterdata.view' }] },
      ],
    };
    expect(selectedPermissionCount(menu, ['menu.products.details.view', 'menu.masterdata.view'])).toBe(2);
    expect(selectedPermissionCount(menu, [])).toBe(0);
  });

  it('优先展示后端返回的具体字段校验原因', () => {
    const message = roleSaveErrorMessage({
      success: false,
      message: '提交内容校验失败',
      data: {
        scope_config: {
          warehouse_ids: ['仓库 99 不属于当前租户。'],
        },
      },
    });
    expect(message).toBe('业务范围 / 仓库：仓库 99 不属于当前租户。');
  });

  it('页面接入已选计数、保存错误和范围请求防串线', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('已选 {{ selectedPermissionCount(menu, roleForm[surface.key]) }}');
    expect(page).toContain('saveError.value = roleSaveErrorMessage(response);');
    expect(page).toContain('const scopeOptionLoads = createRequestSequence();');
    expect(page).toContain('if (!loadToken.isCurrent()) return;');
    expect(page).toContain("roleForm.scope_type === 'custom' && (scopeOptionsLoading.value || Boolean(scopeOptionsError.value))");
    expect(page).toContain("roleForm.scope_type === 'custom' && (scopeOptionsLoading.value || scopeOptionsError.value)");
  });
});
