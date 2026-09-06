import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildMockPermissionPackages } from '../src/api/systemAdmin';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('角色快速分配与内置身份契约', () => {
  it('保留快速/高级两种配置模式和四类角色模板', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    for (const phrase of ['快速分配', '高级配置', '只读人员', '业务操作员', '部门负责人', '安全审计员']) {
      expect(page).toContain(phrase);
    }
    expect(page).toContain('package_selections');
    expect(page).toContain('extra_permission_codes');
    expect(page).toContain('未触及模块保留原有权限');
  });

  it('通过权限包目录接口加载模块档位并声明高风险确认', () => {
    const api = read('src/api/systemAdmin.js');
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(api).toContain('/api/internal/system/permission-packages/');
    expect(page).toContain('highRiskPermissions');
    expect(page).toContain('quickExtraPermissionCodes');
    expect(page).toContain('ElMessageBox.confirm');
    expect(page).toContain('确认授予高风险权限');
    expect(page).toContain('pendingHighRiskPermissionCodes');
    expect(page).toContain('originalPermissionCodes');
    expect(page).toContain('departmentTreeScopeError');
    expect(page).toContain('仅支持 system 模块权限');
    expect(page).toContain('system.roles.manage 需要全部数据范围');
  });

  it('mock 权限包与后端高风险目录一致，operate 不含 manage 而 admin 保留普通 manage', () => {
    const api = read('src/api/systemAdmin.js');
    const mock = read('src/mock/systemAdmin.js');
    for (const code of [
      'system.roles.manage', 'system.users.manage',
      'system.organization.manage', 'config.system.manage'
    ]) {
      expect(api).toContain(`'${code}'`);
      expect(mock).toContain(`code: '${code}'`);
    }
    for (const action of ['run_live_readonly', 'execute', 'start', 'resume', 'record', 'deploy', 'restore']) {
      expect(api).toContain(`'${action}'`);
    }
    expect(api).toContain("const routineDefinitions = actions.filter((item) => !highRisk.includes(item.code))");
    expect(api).toContain("String(item.action || '').split('.').at(-1) !== 'manage'");
    expect(api).toContain('const adminCodes = [...new Set([...readCodes, ...routine])].sort()');
    expect(api).toContain('highRiskPermissionCodes.has(item.code)');
    expect(api).toContain('high_risk_policy');

    const packages = buildMockPermissionPackages().data.packages;
    const systemPackage = packages.find((item) => item.module === 'system');
    const configPackage = packages.find((item) => item.module === 'config');
    const masterdataPackage = packages.find((item) => item.module === 'masterdata');
    const exactHighRisk = [
      'system.roles.manage', 'system.users.manage',
      'system.organization.manage', 'config.system.manage'
    ];
    for (const code of exactHighRisk) {
      const packageItem = code.startsWith('config.') ? configPackage : systemPackage;
      expect(packageItem.high_risk_codes).toContain(code);
      expect(packageItem.levels.operate).not.toContain(code);
      expect(packageItem.levels.admin).not.toContain(code);
    }
    expect(masterdataPackage.levels.operate).not.toContain('masterdata.manage');
    expect(masterdataPackage.levels.admin).toContain('masterdata.manage');
  });

  it('模板只作用于已有模块，none 会清理风险项且 extras 仅提交已触及模块', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('if (selectedModules.length)');
    expect(page).toContain('当前角色尚未选择模块');
    expect(page).toContain("if (level === 'none')");
    expect(page).toContain('permissionModuleForCode(code) !== module');
    expect(page).toContain('quickTouchedModules.value.has(permissionModuleForCode(code))');
  });

  it('显示平台超级管理员与租户管理员的稳定标签', () => {
    const layout = read('src/layouts/MainLayout.vue');
    const drawer = read('src/components/UserSettingsDrawer.vue');
    const mock = read('src/mock/systemAdmin.js');
    expect(layout).toContain('平台超级管理员');
    expect(drawer).toContain('平台超级管理员');
    expect(mock).toContain('租户管理员');
    expect(mock).toContain("role_type: 'builtin'");
  });
});
