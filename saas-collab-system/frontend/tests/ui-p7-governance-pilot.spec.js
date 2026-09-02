import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { normalizeLoginResponse } from '../src/api/auth';
import { canAccessPath } from '../src/router/menu';
import { permissionLabel } from '../src/utils/permissionLabels';
import { mockAuthUser, mockCurrentUser } from '../src/mock/auth';
import { mockCapacityObservations } from '../src/mock/pilot';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('UI-P7 governance and controlled pilot', () => {
  it('normalizes the existing JWT login contract without weakening business envelopes', () => {
    expect(normalizeLoginResponse({ access: 'demo-access', refresh: 'demo-refresh' })).toEqual({
      success: true,
      code: 'OK',
      message: 'success',
      data: { access: 'demo-access', refresh: 'demo-refresh' }
    });
    expect(normalizeLoginResponse({ access: 'missing-refresh' })).toMatchObject({
      success: false,
      code: 'INVALID_AUTH_RESPONSE',
      data: null
    });
  });

  it('registers every page with an exact internal permission contract', () => {
    const contracts = [
      ['/governance/api-contracts', 'governance.api.view'],
      ['/governance/assistants', 'governance.assistants.view'],
      ['/pilot/readiness', 'pilot.readiness.view'],
      ['/pilot/topology', 'pilot.topology.view'],
      ['/pilot/recovery', 'pilot.recovery.view'],
      ['/pilot/releases', 'pilot.release.view'],
      ['/pilot/capacity', 'pilot.capacity.view']
    ];
    for (const [route, permission] of contracts) {
      expect(canAccessPath({ user_type: 'internal', permissions: [permission] }, route)).toBe(true);
      expect(canAccessPath({ user_type: 'internal', permissions: [] }, route)).toBe(false);
      expect(canAccessPath({ user_type: 'external', permissions: [permission] }, route)).toBe(false);
    }
  });

  it('keeps production action permissions separate from record and view permissions', () => {
    const pages = [
      read('src/views/pilot/P8WorkflowWorkspace.vue'),
      read('src/views/pilot/PilotWorkflow.vue')
    ].join('\n');
    expect(pages).toContain("pilot.performance.execute");
    expect(pages).toContain("pilot.recovery.execute");
    expect(pages).toContain("pilot.release.execute");
    expect(pages).toContain("pilot.release.rollback.execute");
    expect(pages).not.toMatch(/canRecord.*execute|record.*execute/i);
    expect(permissionLabel('pilot.performance.execute')).toBe('执行性能验证');
    expect(permissionLabel('pilot.recovery.execute')).toBe('执行恢复作业');
    expect(permissionLabel('pilot.release.execute')).toBe('执行生产部署');
    expect(permissionLabel('pilot.release.rollback.execute')).toBe('执行生产回滚');
  });

  it('includes execution permissions in the local candidate user returned by mockCurrentUser', () => {
    const executionPermissions = [
      'pilot.performance.execute',
      'pilot.recovery.execute',
      'pilot.release.execute',
      'pilot.release.rollback.execute'
    ];
    expect(mockAuthUser.permissions).toEqual(expect.arrayContaining(executionPermissions));
    expect(mockCurrentUser()).toMatchObject({ success: true, data: { permissions: expect.arrayContaining(executionPermissions) } });
  });

  it('uses only internal governance and pilot API partitions', () => {
    const governance = read('src/api/governance.js');
    const pilot = read('src/api/pilot.js');
    expect(governance).toContain('/api/internal/governance/');
    expect(pilot).toContain('/api/internal/pilot/');
    expect(`${governance}${pilot}`).not.toMatch(/\/api\/rpa\/|\/api\/finance\/|\/admin\//);
  });

  it('uses live governance and pilot APIs without fallback or forced capability downgrades', () => {
    const governance = read('src/api/governance.js');
    const pilot = read('src/api/pilot.js');
    expect(governance).toContain("import { requestApi } from './request'");
    expect(pilot).toContain("import { requestApi } from './request'");
    expect(`${governance}${pilot}`).not.toContain('requestWithMockFallback');
    expect(`${governance}${pilot}`).not.toMatch(/requestWithMockFallback|api_status = ['\"](?:sandbox|pending|mock)/);
    expect(governance).toContain('/api/internal/governance/api-contracts/check-mock/');
    expect(pilot).toContain('/api/internal/pilot/topology/verify-mock/');
    expect(governance).toContain('/assistants/${id}/evaluations/');
    expect(governance).toContain('/assistant-evaluations/${id}/');
    expect(pilot).toContain('/performance-runs/${id}/execute/');
    expect(pilot).toContain('/recovery-plans/${id}/execute/');
    expect(pilot).toContain('/release-plans/${id}/execute/');
    expect(pilot).toContain('/release-plans/${id}/execute-rollback/');
    expect(pilot).toContain('/executions/');
  });

  it('does not expose infrastructure or high-risk execution controls', () => {
    const pages = [
      read('src/views/pilot/ReadinessDashboard.vue'), read('src/views/pilot/TopologyOverview.vue'),
      read('src/views/pilot/CapacityDashboard.vue'), read('src/views/pilot/PilotWorkflow.vue')
    ].join('\n');
    expect(pages).not.toMatch(/WebShell|executeSql|dockerExec|sshCommand|deployNow|restoreNow|connectPlatform|evaluate-mock|verify-mock/);
    expect(pages).toContain('执行部署');
    expect(pages).toContain('执行恢复');
    expect(pages).toContain('执行回滚');
  });

  it('uses idempotency keys for every write API', () => {
    expect(read('src/api/governance.js')).toMatch(/['\"]Idempotency-Key['\"]:\s*idempotency\(/);
    expect(read('src/api/pilot.js')).toMatch(/['\"]Idempotency-Key['\"]:\s*idempotency\(/);
  });

  it('uses the exact UI-P7 response fields in mocks and pages', () => {
    const governanceMock = read('src/mock/governance.js');
    const pilotMock = read('src/mock/pilot.js');
    expect(governanceMock).toMatch(/permission:|scope_keys:|response_schema_version:|evidence_status:/);
    expect(governanceMock).toMatch(/capability_declarations:|data_classes:|tool_allowlist:/);
    expect(pilotMock).toMatch(/gate_code:|evidence_at:|evidence_refs:/);
    expect(pilotMock).toMatch(/masked_endpoint:|health_status:|checked_at:/);
    expect(pilotMock).toMatch(/threshold:|expires_at:|status: 'normal'|status: 'critical'/);
    expect(mockCapacityObservations({ status: 'normal' }).data.results).toMatchObject([{ status: 'normal', threshold: 70 }]);
    expect(mockCapacityObservations({ status: 'critical' }).data.results).toMatchObject([{ status: 'critical', threshold: 90 }]);
  });

  it('loads governance detail routes and exposes every controlled workflow action', () => {
    const governancePage = read('src/views/governance/GovernanceCatalog.vue');
    const workflowPage = read('src/views/pilot/PilotWorkflow.vue');
    expect(governancePage).toContain('route.params.id');
    expect(governancePage).toContain('loadDetail(route.params.id, false)');
    for (const permission of ['.plan', '.review', '.execute', 'pilot.release.rollback.execute']) expect(`${workflowPage}${read('src/views/pilot/P8WorkflowWorkspace.vue')}`).toContain(permission);
    for (const action of ['schedule', 'execute', 'cancel', 'approve-rollback']) expect(`${workflowPage}${read('src/api/pilot.js')}`).toContain(action);
  });

  it('exposes execution state and does not manufacture workflow results in views', () => {
    const pages = [read('src/views/pilot/P8WorkflowWorkspace.vue'), read('src/views/pilot/PilotWorkflow.vue'), read('src/views/pilot/ControlRoom.vue')].join('\n');
    expect(pages).toContain('queued');
    expect(pages).toContain('running');
    expect(pages).toContain('passed');
    expect(pages).toContain('failed');
    expect(pages).toContain('fetchExecutions');
    expect(pages).not.toMatch(/demo[-_]|fixed demo|Mock|mock/i);
  });

  it('keeps production operation controls behind explicit confirmation and permission', () => {
    const release = read('src/views/pilot/PilotWorkflow.vue');
    const p8 = read('src/views/pilot/P8WorkflowWorkspace.vue');
    expect(release).toContain('ElMessageBox.confirm');
    expect(p8).toContain('ElMessageBox.confirm');
    expect(release).toContain('pilot.release.rollback.execute');
    expect(release).toContain('row.rollback_approval_ref');
  });
});
