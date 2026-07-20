import { requestWithMockFallback, withApiStatus } from './request';
import { mockCapacityObservations, mockCapacitySummary, mockCreateRecoveryPlan, mockCreateReleasePlan, mockP8Action, mockP8Create, mockP8Detail, mockP8List, mockP8Patch, mockPilotControlRoom, mockReadiness, mockRecoveryAction, mockRecoveryDrills, mockRecoveryPlan, mockRecoveryPlans, mockRecoveryResult, mockReleaseAction, mockReleasePlan, mockReleasePlans, mockTopology, mockTopologyVerify } from '../mock/pilot';

const sandbox = async (request) => {
  const response = withApiStatus(await request, 'sandbox');
  if (response?.success && response.data?.api_status === 'connected') response.data.api_status = 'sandbox';
  return response;
};
const idempotency = () => `ui-p7-pilot-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const action = (url, data, mockHandler, moduleName) => sandbox(requestWithMockFallback({ method: 'post', url, data, headers: { 'Idempotency-Key': idempotency() } }, mockHandler, moduleName));

export const fetchPilotReadiness = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/readiness/', params }, mockReadiness, 'pilot.readiness'));
export const fetchPilotTopology = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/topology/', params }, mockTopology, 'pilot.topology'));
export const verifyPilotTopologyMock = (payload) => action('/api/internal/pilot/topology/verify-mock/', payload, mockTopologyVerify, 'pilot.topology.verify');
export const fetchCapacitySummary = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/capacity/summary/', params }, mockCapacitySummary, 'pilot.capacity.summary'));
export const fetchCapacityObservations = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/capacity/observations/', params }, () => mockCapacityObservations(params), 'pilot.capacity.observations'));
export const fetchRecoveryPlans = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/recovery-plans/', params }, mockRecoveryPlans, 'pilot.recovery'));
export const fetchRecoveryPlan = (id) => sandbox(requestWithMockFallback({ method: 'get', url: `/api/internal/pilot/recovery-plans/${id}/` }, mockRecoveryPlan, 'pilot.recovery.detail'));
export const createRecoveryPlan = (payload) => action('/api/internal/pilot/recovery-plans/', payload, mockCreateRecoveryPlan, 'pilot.recovery.create');
export const runRecoveryAction = (id, actionName, payload) => action(`/api/internal/pilot/recovery-plans/${id}/${actionName}/`, payload, () => mockRecoveryAction(id, actionName, payload), `pilot.recovery.${actionName}`);
export const fetchRecoveryDrills = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/recovery-drills/', params }, () => mockRecoveryDrills(params), 'pilot.recovery.drills'));
export const recordRecoveryResult = (id, payload) => action(`/api/internal/pilot/recovery-drills/${id}/record-result/`, payload, () => mockRecoveryResult(id, payload), 'pilot.recovery.result');
export const fetchReleasePlans = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/release-plans/', params }, mockReleasePlans, 'pilot.release'));
export const fetchReleasePlan = (id) => sandbox(requestWithMockFallback({ method: 'get', url: `/api/internal/pilot/release-plans/${id}/` }, mockReleasePlan, 'pilot.release.detail'));
export const createReleasePlan = (payload) => action('/api/internal/pilot/release-plans/', payload, mockCreateReleasePlan, 'pilot.release.create');
export const runReleaseAction = (id, actionName, payload) => action(`/api/internal/pilot/release-plans/${id}/${actionName}/`, payload, () => mockReleaseAction(id, actionName, payload), `pilot.release.${actionName}`);

const p8Paths = { security: 'security-reviews', verification: 'verification-runs', performance: 'performance-runs', entry: 'entry-decisions' };
const p8Pending = async (promise) => {
  const response = await promise;
  if (response?.success && response.data?.api_status === 'connected') response.data.api_status = 'pending';
  return response;
};
const p8Action = (kind, id, actionName, payload) => p8Pending(requestWithMockFallback({ method: 'post', url: `/api/internal/pilot/${p8Paths[kind]}/${id}/${actionName}/`, data: payload, headers: { 'Idempotency-Key': `ui-p8-${Date.now()}-${Math.random().toString(16).slice(2)}` } }, () => mockP8Action(kind, id, actionName, payload), `pilot.${kind}.${actionName}`));

export const fetchPilotControlRoom = (params) => p8Pending(requestWithMockFallback({ method: 'get', url: '/api/internal/pilot/control-room/', params }, mockPilotControlRoom, 'pilot.control'));
export const fetchP8Resources = (kind, params = {}) => p8Pending(requestWithMockFallback({ method: 'get', url: `/api/internal/pilot/${p8Paths[kind]}/`, params }, () => mockP8List(kind), `pilot.${kind}`));
export const fetchP8Resource = (kind, id) => p8Pending(requestWithMockFallback({ method: 'get', url: `/api/internal/pilot/${p8Paths[kind]}/${id}/` }, () => mockP8Detail(kind, id), `pilot.${kind}.detail`));
export const createP8Resource = (kind, payload) => p8Pending(requestWithMockFallback({ method: 'post', url: `/api/internal/pilot/${p8Paths[kind]}/`, data: payload, headers: { 'Idempotency-Key': `ui-p8-create-${Date.now()}-${Math.random().toString(16).slice(2)}` } }, () => mockP8Create(kind, payload), `pilot.${kind}.create`));
export const patchP8Resource = (kind, id, payload) => p8Pending(requestWithMockFallback({ method: 'patch', url: `/api/internal/pilot/${p8Paths[kind]}/${id}/`, data: payload }, () => mockP8Patch(kind, id, payload), `pilot.${kind}.patch`));
export const runP8Action = p8Action;
