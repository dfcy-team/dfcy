import { successResponse } from './index';

export const mockReadiness = () => successResponse({
  environment_id: 'controlled-pilot', overall_status: 'in_progress', evaluated_at: '2026-07-17T00:00:00Z', api_status: 'mock',
  gates: [
    { gate_code: 'ci', name: 'CI evidence', status: 'passed', evidence_at: '2026-07-17T00:00:00Z', expires_at: '2026-08-17T00:00:00Z', blockers: [], owner: 'architecture', evidence_refs: ['demo-ci-evidence'] },
    { gate_code: 'recovery', name: 'Recovery evidence', status: 'in_progress', evidence_at: '2026-07-17T00:00:00Z', expires_at: '2026-08-17T00:00:00Z', blockers: [], owner: 'architecture', evidence_refs: ['demo-recovery-evidence'] }
  ]
});

export const mockTopology = () => successResponse({
  environment_id: 'controlled-pilot', generated_at: '2026-07-17T00:00:00Z', api_status: 'mock',
  services: [
    { service_name: 'nginx', host_role: 'application', network_zone: 'controlled_app', masked_endpoint: 'nginx@controlled_app', exposure: 'controlled_lan', health_status: 'healthy', checked_at: '2026-07-17T00:00:00Z' },
    { service_name: 'mysql', host_role: 'database', network_zone: 'controlled_db', masked_endpoint: 'mysql@controlled_db', exposure: 'app_host_only', health_status: 'healthy', checked_at: '2026-07-17T00:00:00Z' }
  ]
});
export const mockTopologyVerify = () => successResponse({ valid: true, violations: [], checked_at: '2026-07-17T00:00:00Z', evidence_status: 'fixed_demo', api_status: 'mock' });

const recovery = [{ id: 1, environment_id: 'controlled-pilot', name: 'Demo recovery drill', rpo_minutes: 30, rto_minutes: 60, status: 'draft', version: 1, audit_ref: 'pilot-audit:pending' }];
const releases = [{ id: 1, environment_id: 'controlled-pilot', release_channel: 'demo', commit_sha: '1111111111111111111111111111111111111111', tag: 'demo-ui-p7', status: 'draft', version: 1, manual_context: '', rollback_approval_ref: '', audit_ref: 'pilot-audit:pending' }];
const drills = [];
const page = (items) => ({ count: items.length, next: null, previous: null, results: items.map((item) => ({ ...item })), api_status: 'mock' });

function nextStatus(actionName, payload) {
  return {
    'submit-review': 'review_pending', approve: 'approved', reject: 'rejected', schedule: 'scheduled',
    start: 'running', resume: 'running', cancel: 'cancelled',
    'record-result': payload?.result_status,
    'approve-rollback': 'rollback_required', 'resume-rollback': 'rollback_required',
    'record-rollback': payload?.rollback_status
  }[actionName];
}

export const mockRecoveryPlans = () => successResponse(page(recovery));
export const mockRecoveryPlan = (id = 1) => successResponse({ ...(recovery.find((item) => item.id === Number(id)) || recovery[0]), api_status: 'mock' });
export const mockCreateRecoveryPlan = () => {
  const item = { ...recovery[0], id: Math.max(...recovery.map(({ id }) => id), 0) + 1, version: 1 };
  recovery.unshift(item);
  return successResponse({ ...item, api_status: 'mock' });
};
export const mockRecoveryAction = (id, actionName, payload = {}) => {
  const item = recovery.find((entry) => entry.id === Number(id)) || recovery[0];
  item.status = nextStatus(actionName, payload) || item.status;
  item.version += 1;
  if (actionName === 'start') {
    drills.unshift({ id: drills.length + 1, recovery_plan_id: item.id, environment_id: item.environment_id, status: 'running', version: 1, audit_ref: `pilot-audit:${item.version}` });
  }
  item.audit_ref = `pilot-audit:${item.version}`;
  return successResponse({ ...item, drill: actionName === 'start' ? { ...drills[0] } : undefined, idempotent_replay: false, api_status: 'mock' });
};
export const mockRecoveryDrills = (params = {}) => successResponse(page(drills.filter((item) => !params.recovery_plan_id || item.recovery_plan_id === Number(params.recovery_plan_id))));
export const mockRecoveryResult = (id, payload = {}) => {
  const drill = drills.find((item) => item.id === Number(id));
  if (drill) { drill.status = payload.result_status; drill.version += 1; }
  const plan = recovery.find((item) => item.id === drill?.recovery_plan_id) || recovery[0];
  plan.status = payload.result_status; plan.version += 1;
  return successResponse({ drill: { ...drill }, plan: { ...plan }, idempotent_replay: false, api_status: 'mock' });
};

export const mockReleasePlans = () => successResponse(page(releases));
export const mockReleasePlan = (id = 1) => successResponse({ ...(releases.find((item) => item.id === Number(id)) || releases[0]), api_status: 'mock' });
export const mockCreateReleasePlan = () => {
  const item = { ...releases[0], id: Math.max(...releases.map(({ id }) => id), 0) + 1, version: 1 };
  releases.unshift(item);
  return successResponse({ ...item, api_status: 'mock' });
};
export const mockReleaseAction = (id, actionName, payload = {}) => {
  const item = releases.find((entry) => entry.id === Number(id)) || releases[0];
  item.status = nextStatus(actionName, payload) || item.status;
  item.version += 1;
  if (actionName === 'record-result' && payload.result_status === 'manual_required') item.manual_context = 'release';
  if (actionName === 'record-result' && payload.result_status === 'rollback_required') item.manual_context = '';
  if (actionName === 'approve-rollback') item.rollback_approval_ref = payload.rollback_approval_ref;
  if (actionName === 'record-rollback' && payload.rollback_status === 'manual_required') item.manual_context = 'rollback';
  item.audit_ref = `pilot-audit:${item.version}`;
  return successResponse({ ...item, idempotent_replay: false, api_status: 'mock' });
};

export const mockCapacitySummary = () => successResponse({ environment_id: 'controlled-pilot', window_minutes: 15, quality_status: 'partial', api_status: 'mock', metrics: [
  { id: 1, environment_id: 'controlled-pilot', service_name: 'backend', metric_code: 'cpu_percent', value: 31.5, unit: '%', threshold: 70, status: 'normal', source: 'fixed_demo', observed_at: '2026-07-17T00:00:00Z', expires_at: '2026-07-17T00:15:00Z', is_missing: false },
  { id: 2, environment_id: 'controlled-pilot', service_name: 'worker', metric_code: 'queue_depth', value: 96, unit: 'items', threshold: 90, status: 'critical', source: 'fixed_demo', observed_at: '2026-07-17T00:00:00Z', expires_at: '2026-07-17T00:15:00Z', is_missing: false }
] });
export const mockCapacityObservations = (params = {}) => {
  const metrics = mockCapacitySummary().data.metrics.filter((item) => !params.status || item.status === params.status);
  return successResponse(page(metrics));
};
