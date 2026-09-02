import { requestApi } from './request';

const idempotency = (prefix = 'ui-pilot') => `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const write = (url, data, prefix = 'ui-pilot-write') => requestApi({
  method: 'post',
  url,
  data,
  headers: { 'Idempotency-Key': idempotency(prefix) }
});

export const fetchPilotReadiness = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/readiness/', params });
export const fetchPilotTopology = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/topology/', params });
export const verifyPilotTopology = (payload) => write('/api/internal/pilot/topology/verify-mock/', payload, 'ui-pilot-topology-verify');
export const fetchCapacitySummary = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/capacity/summary/', params });
export const fetchCapacityObservations = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/capacity/observations/', params });

export const fetchRecoveryPlans = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/recovery-plans/', params });
export const fetchRecoveryPlan = (id) => requestApi({ method: 'get', url: `/api/internal/pilot/recovery-plans/${id}/` });
export const createRecoveryPlan = (payload) => write('/api/internal/pilot/recovery-plans/', payload, 'ui-pilot-recovery-create');
export const runRecoveryAction = (id, actionName, payload) => write(`/api/internal/pilot/recovery-plans/${id}/${actionName}/`, payload, `ui-pilot-recovery-${actionName}`);
export const executeRecoveryPlan = (id, payload) => write(`/api/internal/pilot/recovery-plans/${id}/execute/`, payload, 'ui-pilot-recovery-execute');
export const fetchRecoveryDrills = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/recovery-drills/', params });
export const recordRecoveryResult = (id, payload) => write(`/api/internal/pilot/recovery-drills/${id}/record-result/`, payload, 'ui-pilot-recovery-result');

export const fetchReleasePlans = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/release-plans/', params });
export const fetchReleasePlan = (id) => requestApi({ method: 'get', url: `/api/internal/pilot/release-plans/${id}/` });
export const createReleasePlan = (payload) => write('/api/internal/pilot/release-plans/', payload, 'ui-pilot-release-create');
export const runReleaseAction = (id, actionName, payload) => write(`/api/internal/pilot/release-plans/${id}/${actionName}/`, payload, `ui-pilot-release-${actionName}`);
export const executeReleasePlan = (id, payload) => write(`/api/internal/pilot/release-plans/${id}/execute/`, payload, 'ui-pilot-release-execute');
export const executeReleaseRollback = (id, payload) => write(`/api/internal/pilot/release-plans/${id}/execute-rollback/`, payload, 'ui-pilot-release-rollback');

const p8Paths = { security: 'security-reviews', verification: 'verification-runs', performance: 'performance-runs', entry: 'entry-decisions' };

export const fetchPilotControlRoom = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/control-room/', params });
export const fetchExecutions = (params = {}) => requestApi({ method: 'get', url: '/api/internal/pilot/executions/', params });
export const fetchExecution = (id) => requestApi({ method: 'get', url: `/api/internal/pilot/executions/${id}/` });

export const fetchP8Resources = (kind, params = {}) => requestApi({
  method: 'get',
  url: `/api/internal/pilot/${p8Paths[kind]}/`,
  params
});

export const fetchP8Resource = (kind, id) => requestApi({
  method: 'get',
  url: `/api/internal/pilot/${p8Paths[kind]}/${id}/`
});

export const createP8Resource = (kind, payload) => write(
  `/api/internal/pilot/${p8Paths[kind]}/`,
  payload,
  `ui-p8-${kind}-create`
);

export const patchP8Resource = (kind, id, payload) => requestApi({
  method: 'patch',
  url: `/api/internal/pilot/${p8Paths[kind]}/${id}/`,
  data: payload,
  headers: { 'Idempotency-Key': idempotency(`ui-p8-${kind}-patch`) }
});

export const runP8Action = (kind, id, actionName, payload) => write(
  `/api/internal/pilot/${p8Paths[kind]}/${id}/${actionName}/`,
  payload,
  `ui-p8-${kind}-${actionName}`
);

export const executePerformanceRun = (id, payload) => write(
  `/api/internal/pilot/performance-runs/${id}/execute/`,
  payload,
  'ui-pilot-performance-execute'
);
