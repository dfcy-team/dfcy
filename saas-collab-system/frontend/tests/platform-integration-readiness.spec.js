import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(path.resolve(process.cwd(), 'src/views/settings/PlatformIntegrationReadiness.vue'), 'utf8');
const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/integrations.js'), 'utf8');

describe('平台接入真实准备度契约', () => {
  it('读取租户范围内的后端真实准备度，不再读取静态 Mock', () => {
    expect(page).toContain('fetchPlatformIntegrationReadiness');
    expect(page).not.toContain('mockPlatformIntegrationReadiness');
    expect(api).toContain('/api/internal/integrations/readiness/');
  });

  it('展示配置概况和可执行的待处理项', () => {
    expect(page).toContain('config_summary');
    expect(page).toContain('blocker_summary');
    expect(page).toContain('平台生产只读状态');
    expect(page).toContain('全局安全门');
    expect(page).toContain('只读同步开关');
  });

  it('提供租户范围内的整改和生产只读审批闭环', () => {
    expect(page).toContain('修复合同版本');
    expect(page).toContain('审批生产只读');
    expect(page).toContain('撤销只读审批');
    expect(page).toContain('维护凭据并执行检查');
    expect(page).toContain('授权 Shopee 店铺');
    expect(api).toContain('/repair-contract/');
    expect(api).toContain('/readonly-approval/');
  });

  it('审批动作按现有细粒度权限控制且不开放生产写入', () => {
    expect(page).toContain("auth.hasPermission('integrations.config.update')");
    expect(page).toContain("auth.hasPermission('integrations.config.verify')");
    expect(page).toContain('生产写入始终关闭');
    expect(page).not.toContain('sync_write_enabled: true');
  });
});
