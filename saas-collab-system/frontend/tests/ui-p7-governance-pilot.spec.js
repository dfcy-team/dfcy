import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { normalizeLoginResponse } from '../src/api/auth';
import { mockAuthUser } from '../src/mock/auth';
import { mockCapacityObservations, mockRecoveryAction, mockRecoveryPlan, mockReleaseAction, mockReleasePlan } from '../src/mock/pilot';
import { canAccessPath } from '../src/router/menu';

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

  it('grants mock actions by exact action permission', () => {
    expect(mockAuthUser.permissions).toEqual(expect.arrayContaining([
      'governance.api.check', 'governance.assistants.evaluate', 'pilot.topology.verify',
      'pilot.recovery.plan', 'pilot.recovery.review', 'pilot.recovery.record',
      'pilot.release.plan', 'pilot.release.review', 'pilot.release.record', 'pilot.release.rollback'
    ]));
  });

  it('uses only internal governance and pilot API partitions', () => {
    const governance = read('src/api/governance.js');
    const pilot = read('src/api/pilot.js');
    expect(governance).toContain('/api/internal/governance/');
    expect(pilot).toContain('/api/internal/pilot/');
    expect(`${governance}${pilot}`).not.toMatch(/\/api\/rpa\/|\/api\/finance\/|\/admin\//);
  });

  it('keeps fixed checks in mock and real evidence in sandbox until E2E', () => {
    const governance = read('src/api/governance.js');
    const pilot = read('src/api/pilot.js');
    expect(governance).toContain("response.data.api_status = 'sandbox'");
    expect(pilot).toContain("response.data.api_status = 'sandbox'");
    expect(read('src/mock/governance.js')).toContain("evidence_status: 'fixed_demo'");
    expect(read('src/mock/pilot.js')).toContain("api_status: 'mock'");
  });

  it('does not expose infrastructure or high-risk execution controls', () => {
    const pages = [
      read('src/views/pilot/ReadinessDashboard.vue'), read('src/views/pilot/TopologyOverview.vue'),
      read('src/views/pilot/CapacityDashboard.vue'), read('src/views/pilot/PilotWorkflow.vue')
    ].join('\n');
    expect(pages).not.toMatch(/WebShell|executeSql|dockerExec|sshCommand|deployNow|restoreNow|connectPlatform/);
    expect(pages).toContain('不会执行部署');
    expect(pages).toContain('仅记录已在受控主机完成的外部操作');
  });

  it('uses idempotency keys for every write API', () => {
    expect(read('src/api/governance.js')).toContain("'Idempotency-Key': idempotency()");
    expect(read('src/api/pilot.js')).toContain("'Idempotency-Key': idempotency()");
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
    for (const permission of ['.plan', '.review', '.record', 'pilot.release.rollback']) expect(workflowPage).toContain(permission);
    for (const action of ['schedule', 'start', 'record-result', 'resume', 'cancel', 'approve-rollback', 'resume-rollback', 'record-rollback']) expect(workflowPage).toContain(action);
  });

  it('keeps mock workflows stateful without adding execution endpoints', () => {
    const mock = read('src/mock/pilot.js');
    expect(mock).toContain("'submit-review': 'review_pending'");
    expect(mock).toContain("'record-rollback': payload?.rollback_status");
    expect(mock).not.toMatch(/dockerExec|sshCommand|executeSql|WebShell|\/api\/rpa\//i);
  });

  it('advances recovery and release dry-run state without executing infrastructure', () => {
    expect(mockRecoveryPlan(1).data.status).toBe('draft');
    expect(mockRecoveryAction(1, 'submit-review', {}).data.status).toBe('review_pending');
    expect(mockRecoveryAction(1, 'approve', {}).data.status).toBe('approved');
    expect(mockReleasePlan(1).data.status).toBe('draft');
    expect(mockReleaseAction(1, 'submit-review', {}).data.status).toBe('review_pending');
    expect(mockReleaseAction(1, 'approve', {}).data.status).toBe('approved');
  });
});
