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

const future = (days = 7) => new Date(Date.now() + days * 86400000).toISOString();
const now = () => new Date().toISOString();
const p8Collections = {
  security: [{ id: 1, code: 'SEC-DEMO-001', review_type: 'network_boundary', environment: 'pilot', scope_summary: 'Demo masked network boundary review', risk_level: 'medium', owner_id: 1, finance_scope: null, evidence_refs: ['demo-security-evidence'], expires_at: future(30), status: 'draft', creator_id: 1, reviewer_id: null, version: 1, audit_ref: 'pilot-audit:pending', created_at: now(), updated_at: now() }],
  verification: [{ id: 1, code: 'VER-DEMO-001', category: 'browser_e2e', environment: 'pilot', target_alias: 'demo-app', data_class: 'synthetic', planned_start_at: future(1), planned_end_at: future(2), success_criteria: ['Demo login flow renders'], evidence_refs: ['demo-verification-evidence'], status: 'draft', result_summary: '', creator_id: 1, reviewer_id: null, recorder_id: null, version: 1, audit_ref: 'pilot-audit:pending', created_at: now(), updated_at: now() }],
  performance: [{ id: 1, code: 'PERF-DEMO-001', scenario: 'Synthetic dashboard read workload', environment: 'pilot', workload_profile: 'synthetic', max_rps: 20, concurrency: 5, duration_seconds: 60, thresholds: { p95_ms_max: 800, error_rate_max: 0.01, cpu_percent_max: 80, memory_percent_max: 80 }, evidence_refs: ['demo-performance-evidence'], status: 'draft', creator_id: 1, reviewer_id: null, recorder_id: null, version: 1, audit_ref: 'pilot-audit:pending', created_at: now(), updated_at: now() }],
  entry: [{ id: 1, code: 'ENTRY-DEMO-001', environment: 'pilot', decision: 'no_go', scope_summary: 'Demo pilot entry decision only', security_review_ids: [1], verification_run_ids: [1], performance_run_ids: [1], recovery_plan_ids: [1], release_plan_ids: [1], expires_at: future(14), status: 'draft', blockers: [{ code: 'DEMO_PENDING', message: 'Demo evidence remains pending.' }], warnings: [], creator_id: 1, reviewer_id: null, version: 1, audit_ref: 'pilot-audit:pending', created_at: now(), updated_at: now() }]
};

const p8Page = (rows) => successResponse({ count: rows.length, next: null, previous: null, results: rows.map((row) => ({ ...row })), api_status: 'mock' });
export const mockPilotControlRoom = () => successResponse({ environment: 'pilot', capability_status: 'sandbox', readiness_status: 'blocked', readiness_score: 25, gate_summary: [{ code: 'security', name: '专项安全准入', status: 'pending', source_type: 'security_review', source_id: 1 }], blockers: [{ code: 'DEMO_PENDING', message: 'Mock 证据不可用于生产准入。', source_type: 'mock', source_id: null }], warnings: [], evidence_counts: { security_reviews: 1, verification_runs: 1, performance_runs: 1, recovery_plans: 1, release_plans: 1 }, stale_sources: [], contract_version: 'UI-P8-R3', refreshed_at: now(), api_status: 'mock' });
export const mockP8List = (kind) => p8Page(p8Collections[kind] || []);
export const mockP8Detail = (kind, id) => {
  const row = (p8Collections[kind] || []).find((item) => item.id === Number(id));
  return row ? successResponse({ ...row, api_status: 'mock' }) : { success: false, code: 'NOT_FOUND', message: 'Demo resource not found.', data: null, http_status: 404 };
};
export const mockP8Create = (kind, payload) => {
  const rows = p8Collections[kind];
  const item = { ...payload, id: Math.max(0, ...rows.map(({ id }) => id)) + 1, code: `${kind.toUpperCase()}-DEMO-${rows.length + 1}`, owner_id: 1, creator_id: 1, reviewer_id: null, recorder_id: null, status: 'draft', version: 1, audit_ref: 'pilot-audit:pending', created_at: now(), updated_at: now(), api_status: 'mock' };
  rows.unshift(item);
  return successResponse({ ...item });
};
export const mockP8Patch = (kind, id, payload) => {
  const row = (p8Collections[kind] || []).find((item) => item.id === Number(id));
  if (!row) return { success: false, code: 'NOT_FOUND', message: 'Demo resource not found.', data: null, http_status: 404 };
  if (row.status !== 'draft' || Number(payload.version) !== Number(row.version)) {
    return { success: false, code: 'STATE_CONFLICT', message: 'Demo draft changed; refresh before retrying.', data: null, http_status: 409 };
  }
  Object.assign(row, payload, { version: row.version + 1, updated_at: now() });
  return successResponse({ ...row, api_status: 'mock' });
};
export const mockP8Action = (kind, id, actionName, payload) => {
  const row = (p8Collections[kind] || []).find((item) => item.id === Number(id));
  if (!row) return { success: false, code: 'NOT_FOUND', message: 'Demo resource not found.', data: null, http_status: 404 };
  const transitions = { submit: 'submitted', approve: 'approved', reject: 'rejected', cancel: 'cancelled' };
  row.status = transitions[actionName] || (payload.result || (payload.result_mode === 'manual_required' ? 'manual_required' : 'passed'));
  row.version += 1;
  row.updated_at = now();
  if (actionName === 'record-result') row.result_summary = payload.result_summary;
  return successResponse({ ...row, api_status: 'mock' });
};
export const mockCapacityObservations = (params = {}) => {
  const metrics = mockCapacitySummary().data.metrics.filter((item) => !params.status || item.status === params.status);
  return successResponse(page(metrics));
};
