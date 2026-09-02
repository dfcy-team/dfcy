import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const requestApi = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi }));

import {
  createAssistantEvaluation,
  fetchAssistantEvaluation
} from '../src/api/governance';
import {
  executePerformanceRun,
  executeRecoveryPlan,
  executeReleasePlan,
  executeReleaseRollback,
  fetchExecutions
} from '../src/api/pilot';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('governance and pilot production execution contract', () => {
  beforeEach(() => {
    requestApi.mockReset();
    requestApi.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: {} });
  });

  it('routes assistant evaluation through a server job and never handles a key in the UI', async () => {
    await createAssistantEvaluation(7, { input: 'real input', expected_output: 'expected', version: 3 });
    await fetchAssistantEvaluation('eval-7');
    expect(requestApi).toHaveBeenNthCalledWith(1, expect.objectContaining({
      method: 'post', url: '/api/internal/governance/assistants/7/evaluations/', data: expect.objectContaining({ input: 'real input', expected_output: 'expected' })
    }));
    expect(requestApi).toHaveBeenNthCalledWith(2, { method: 'get', url: '/api/internal/governance/assistant-evaluations/eval-7/' });
    const page = read('src/views/governance/GovernanceCatalog.vue');
    expect(page).toContain('发起异步评估');
    expect(page).toContain('evaluationForm.scenario');
    expect(page).toContain('evaluationForm.input');
    expect(page).toContain('evaluationForm.expected_output');
    expect(page).toContain('evaluationForm.reason');
    expect(page).toContain('token_usage');
    expect(page).toContain('assistant_output');
    expect(page).toContain('findings');
    // The page must warn operators about forbidden secrets, but it must not
    // render a credential field or embed a credential value in the UI.
    expect(page).toMatch(/public_demo|合成或公开测试数据/);
    expect(page).not.toMatch(/(?:v-model|name|id)=['"][^'"]*(?:api[_-]?key|api[_-]?secret|password|token|cookie)/i);
    expect(page).not.toMatch(/sk-[A-Za-z0-9_-]{12,}/);
    expect(page).not.toMatch(/payload\.data_class|data_class\s*:/);
  });

  it('routes every production execution action and status refresh to internal APIs', async () => {
    await executePerformanceRun(11, { version: 2, target_alias: 'controlled-api' });
    await executeRecoveryPlan(12, { version: 4, reason: 'approved recovery' });
    await executeReleasePlan(13, { version: 5, reason: 'approved release' });
    await executeReleaseRollback(13, { version: 6, rollback_approval_ref: 'rollback-approval' });
    await fetchExecutions({ environment: 'pilot' });
    expect(requestApi.mock.calls.map(([config]) => config.url)).toEqual([
      '/api/internal/pilot/performance-runs/11/execute/',
      '/api/internal/pilot/recovery-plans/12/execute/',
      '/api/internal/pilot/release-plans/13/execute/',
      '/api/internal/pilot/release-plans/13/execute-rollback/',
      '/api/internal/pilot/executions/'
    ]);
    for (const [config] of requestApi.mock.calls.slice(0, 4)) expect(config.headers['Idempotency-Key']).toMatch(/^ui-/);
  });

  it('keeps execution controls permission-gated and confirmation-protected', () => {
    const p8 = read('src/views/pilot/P8WorkflowWorkspace.vue');
    const workflow = read('src/views/pilot/PilotWorkflow.vue');
    const controlRoom = read('src/views/pilot/ControlRoom.vue');
    expect(p8).toContain("auth.hasPermission('pilot.performance.execute')");
    expect(workflow).toContain("'pilot.release.execute'");
    expect(workflow).toContain("'pilot.recovery.execute'");
    expect(workflow).toContain("'pilot.release.rollback.execute'");
    expect(p8).toContain('ElMessageBox.confirm');
    expect(workflow).toContain('ElMessageBox.confirm');
    for (const status of ['queued', 'running', 'passed', 'failed']) expect(`${p8}${workflow}${controlRoom}`).toContain(status);
  });

  it('uses percentage points for the performance error-rate threshold', () => {
    const p8 = read('src/views/pilot/P8WorkflowWorkspace.vue');
    expect(p8).toContain('错误率上限（%）');
    expect(p8).toMatch(/error_rate_max:\s*1/);
    expect(p8).toMatch(/v-model="createForm\.thresholds\.error_rate_max"[^>]*:max="100"[^>]*:step="0\.01"/);
  });

  it('requires an explicit production execution window before deployment or recovery', () => {
    const workflow = read('src/views/pilot/PilotWorkflow.vue');
    expect(workflow).toContain('openSchedule(row)');
    expect(workflow).toContain('scheduleForm.scheduled_at');
    expect(workflow).toContain('isExecutionWindowOpen(row)');
    expect(workflow).toContain(':disabled="!isExecutionWindowOpen(row)"');
    expect(workflow).toContain('默认建议为当前时间后 5 分钟');
    expect(workflow).not.toContain('重试执行');
  });

  it('uses the strict execution collection query contract in the control room', () => {
    const controlRoom = read('src/views/pilot/ControlRoom.vue');
    expect(controlRoom).toContain('fetchExecutions({ page: 1, page_size: 100 })');
    expect(controlRoom).not.toContain('fetchExecutions({ environment:');
  });

  it('does not contain client fallback, forced sandbox status, or manual-only copy', () => {
    const files = [
      'src/api/governance.js', 'src/api/pilot.js',
      'src/views/governance/GovernanceCatalog.vue', 'src/views/pilot/ControlRoom.vue',
      'src/views/pilot/P8WorkflowWorkspace.vue', 'src/views/pilot/PilotWorkflow.vue',
      'src/views/pilot/ReadinessDashboard.vue', 'src/views/pilot/TopologyOverview.vue',
      'src/views/pilot/CapacityDashboard.vue'
    ];
    const source = files.map(read).join('\n');
    expect(source).not.toContain('requestWithMockFallback');
    expect(source).not.toMatch(/requestWithMockFallback|api_status\s*=\s*['\"](?:sandbox|pending|mock)/);
    expect(source).toContain('fixed-demo/mock');
    expect(source).toContain('check-mock');
    expect(source).toContain('verify-mock');
    expect(source).not.toMatch(/不会执行部署|不会自动执行|仅记录已在受控主机完成/);
  });
});
