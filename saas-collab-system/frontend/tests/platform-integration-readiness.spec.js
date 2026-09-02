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
    expect(page).toContain('真实只读接入条件');
  });

  it('不提供生产启用或写入操作', () => {
    expect(page).not.toContain('生产启用禁用');
    expect(page).not.toContain(':actions=');
    expect(page).toContain('生产写入始终关闭');
  });
});
