import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessPath, filterMenuItems, flattenMenuItems } from '../src/router/menu';
import { getActionAccess } from '../src/utils/actionAccess';
import { mockRpaTasks } from '../src/mock/rpa';
import { mockRpaDevices, mockRpaManualQueue, mockRpaStabilityDashboard } from '../src/mock/rpaStability';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const viewer = {
  user_type: 'internal',
  is_superuser: false,
  permissions: ['rpa.tasks.view', 'rpa.devices.view', 'rpa.stability.view']
};
const authFor = (user) => ({
  currentUser: user,
  hasPermission: (...codes) => Boolean(user.is_superuser) || codes.some((code) => user.permissions.includes(code))
});

describe('UI-P3 route and action permissions', () => {
  it('registers task, run, device, manual, lock and signature routes explicitly', () => {
    for (const path of ['/rpa/tasks', '/rpa/runs', '/rpa/devices', '/rpa/manual-queue', '/rpa/stability', '/rpa/account-locks', '/rpa/page-signatures']) {
      expect(canAccessPath(viewer, path), path).toBe(true);
    }
    expect(canAccessPath({ ...viewer, user_type: 'external' }, '/rpa/tasks')).toBe(false);
    expect(canAccessPath({ ...viewer, user_type: 'rpa' }, '/rpa/devices')).toBe(false);
  });

  it('shows management pages but hides actions from view-only users', () => {
    const paths = flattenMenuItems(filterMenuItems(viewer)).map((item) => item.path);
    expect(paths).toContain('/rpa/tasks');
    expect(paths).toContain('/rpa/devices');
    expect(getActionAccess(authFor(viewer), { permission: 'rpa.tasks.manage' }).visible).toBe(false);
    expect(getActionAccess(authFor(viewer), { permission: 'rpa.devices.dry_run' }).allowed).toBe(false);
  });

  it('allows only declared action permissions', () => {
    const operator = { ...viewer, permissions: [...viewer.permissions, 'rpa.tasks.manage', 'rpa.devices.dry_run'] };
    expect(getActionAccess(authFor(operator), { permission: 'rpa.tasks.manage' }).allowed).toBe(true);
    expect(getActionAccess(authFor(operator), { permission: 'rpa.devices.dry_run' }).allowed).toBe(true);
  });
});

describe('UI-P3 API and safety contracts', () => {
  it('uses only internal management paths and canonical runs/devices resources', () => {
    const sources = read('src/api/rpa.js') + read('src/api/rpaStability.js');
    for (const path of ['/api/internal/rpa/tasks/', '/api/internal/rpa/runs/', '/api/internal/rpa/devices/', '/api/internal/rpa/manual-queue/', '/api/internal/rpa/stability/']) {
      expect(sources).toContain(path);
    }
    expect(sources).not.toMatch(/\/api\/rpa\/tasks\/(claim|\$\{id\}\/heartbeat|\$\{id\}\/complete|\$\{id\}\/fail)/);
    expect(sources).not.toContain('/api/finance/');
    expect(sources).not.toContain('/admin/');
  });

  it('keeps mock collections paginated and explicitly marked mock', () => {
    const tasks = mockRpaTasks().data;
    const devices = mockRpaDevices().data;
    const manual = mockRpaManualQueue().data;
    for (const payload of [tasks, devices, manual]) {
      expect(payload.status).toBe('mock');
      expect(payload).toHaveProperty('count');
      expect(Array.isArray(payload.results)).toBe(true);
    }
  });

  it('never exposes device credentials or a production execution control', () => {
    const device = mockRpaDevices().data.results[0];
    const pages = read('src/views/rpa/RPADeviceList.vue') + read('src/views/rpa/RPADeviceDetail.vue');
    expect(device).toHaveProperty('fingerprint_masked');
    expect(device).not.toHaveProperty('token_hash');
    expect(device).not.toHaveProperty('ip_whitelist');
    expect(pages).toContain('production_disabled');
    expect(pages).not.toMatch(/真实平台连接|生产执行/);
  });

  it('keeps task and run state machines separate and actions state-bound', () => {
    const taskPage = read('src/views/rpa/RPATaskList.vue');
    const runPage = read('src/views/rpa/RPAAttemptList.vue');
    expect(taskPage).toContain("['failed', 'manual_required'].includes(row.status)");
    expect(taskPage).toContain("row.status !== 'manual_required'");
    expect(runPage).toContain('运行状态');
    expect(runPage).not.toContain('retryRpaMock');
  });

  it('keeps stability mock states inside the frozen task and run contracts', () => {
    const payload = mockRpaStabilityDashboard().data;
    const taskStates = new Set(['pending', 'claimed', 'running', 'success', 'failed', 'retrying', 'manual_required', 'cancelled']);
    const runStates = new Set(['claimed', 'running', 'success', 'failed', 'retrying', 'manual_required', 'cancelled']);
    expect(payload.manual_required).toBe(1);
    expect(payload.boundary).toBe('internal_read_only_no_agent_execution');
    expect(payload.task_states.length).toBeGreaterThan(0);
    expect(payload.run_states.length).toBeGreaterThan(0);
    expect(payload.task_states.every((item) => taskStates.has(item.status))).toBe(true);
    expect(payload.run_states.every((item) => runStates.has(item.status))).toBe(true);
    expect(JSON.stringify(payload)).not.toContain('retry_wait');
  });

  it('labels connection capability from API evidence rather than task status', () => {
    const resource = read('src/components/RPAResourcePage.vue');
    const detail = read('src/views/rpa/RPATaskDetail.vue');
    expect(resource).toContain("data.api_status || data.connection_status || data.status || 'mock'");
    expect(detail).toContain("response.data?.api_status || (useMock ? 'mock' : 'connected')");
    expect(detail).not.toContain("response.data?.api_status || response.data?.status");
  });
});
