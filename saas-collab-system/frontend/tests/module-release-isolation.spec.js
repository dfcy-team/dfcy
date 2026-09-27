import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  mockModuleRelease,
  mockCreateModuleReleaseVersion,
  mockApproveModuleReleaseVersion
} from '../src/mock/moduleRelease';
import { mockProductionIntegrationSettings } from '../src/mock/productionSettings';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('模块发布与生产配置隔离', () => {
  it('模块页面只调用独立接口', () => {
    const page = read('src/views/settings/ModuleReleaseControl.vue');
    const api = read('src/api/integrations.js');
    expect(page).toContain('fetchModuleRelease()');
    expect(page).toContain('createModuleReleaseVersion(');
    expect(page).toContain('approveModuleReleaseVersion(');
    expect(page).toContain('rollbackModuleReleaseVersion(');
    expect(page).not.toContain('createProductionIntegrationSettingsVersion');
    expect(api).toContain("url: '/api/internal/integrations/module-release/versions/'");
    const productionPage = read('src/views/settings/ProductionIntegrationSettings.vue');
    expect(productionPage).toContain('hasLegacyModuleData(scope.row)');
    expect(productionPage).toContain('该历史版本混入模块发布配置，不能审批');
  });

  it('审批模块版本不改变生产配置 Mock 数据', () => {
    const before = mockProductionIntegrationSettings().data.effective_config;
    const submitted = mockCreateModuleReleaseVersion({ value: { modules: { core: 'disabled' } } });
    expect(submitted.success).toBe(true);
    expect(mockApproveModuleReleaseVersion(submitted.data.version.id).success).toBe(true);
    expect(mockModuleRelease().data.effective_config.modules.core).toBe('disabled');
    expect(mockProductionIntegrationSettings().data.effective_config).toEqual(before);
  });
});
