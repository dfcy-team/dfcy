import { requestWithMockFallback, withApiStatus } from './request';
import { mockCapacityObservations, mockCapacitySummary, mockCreateRecoveryPlan, mockCreateReleasePlan, mockReadiness, mockRecoveryAction, mockRecoveryDrills, mockRecoveryPlan, mockRecoveryPlans, mockRecoveryResult, mockReleaseAction, mockReleasePlan, mockReleasePlans, mockTopology, mockTopologyVerify } from '../mock/pilot';

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
