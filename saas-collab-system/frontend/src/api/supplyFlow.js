import { requestWithMockFallback } from './request';
import {
  mockConsolidationAction,
  mockCreateConsolidation,
  mockCreateShipment,
  mockCreateSite,
  mockDeactivateSite,
  mockFetchConsolidation,
  mockFetchConsolidations,
  mockFetchShipment,
  mockFetchShipments,
  mockFetchSites,
  mockShipmentAction,
  mockUpdateSite
} from '../mock/supplyFlow';

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map((key) => `${key}:${canonical(value[key])}`).join('|')}}`;
  return JSON.stringify(value ?? null);
}

/** Stable per-resource/action key: repeated clicks/retries reuse the same key. */
export const idempotencyKey = (action, resourceId, payload = {}) => {
  const raw = `${action}:${resourceId ?? 'new'}:${canonical(payload)}`;
  let hash = 2166136261;
  for (let index = 0; index < raw.length; index += 1) hash = Math.imul(hash ^ raw.charCodeAt(index), 16777619);
  return `sc-client3-${action}-${resourceId ?? 'new'}-${(hash >>> 0).toString(16)}`.slice(0, 128);
};

const internal = (method, url, data, fallback, moduleName, action, id) => requestWithMockFallback(
  { method, url, data, headers: method.toLowerCase() === 'get' ? undefined : { 'Idempotency-Key': idempotencyKey(action, id, data) } },
  fallback,
  moduleName
);

export const fetchConsolidationSites = (params = {}) => internal('get', '/api/internal/supply-chain/consolidations/sites/', params, () => mockFetchSites(params), 'supply.consolidation-site.view');
export const createConsolidationSite = (payload) => internal('post', '/api/internal/supply-chain/consolidations/sites/', payload, () => mockCreateSite(payload), 'supply.consolidation-site.manage', 'site-create');
export const updateConsolidationSite = (id, payload) => internal('put', `/api/internal/supply-chain/consolidations/sites/${id}/`, payload, () => mockUpdateSite(id, payload), 'supply.consolidation-site.manage', id);
export const deactivateConsolidationSite = (id, payload) => internal('post', `/api/internal/supply-chain/consolidations/sites/${id}/actions/deactivate/`, payload, () => mockDeactivateSite(id), 'supply.consolidation-site.manage', id);

export const fetchConsolidations = (params = {}) => internal('get', '/api/internal/supply-chain/consolidations/consolidations/', params, () => mockFetchConsolidations(params), 'supply.consolidation.view');
export const fetchConsolidation = (id) => internal('get', `/api/internal/supply-chain/consolidations/consolidations/${id}/`, undefined, () => mockFetchConsolidation(id), 'supply.consolidation.view', id);
export const createConsolidation = (payload) => internal('post', '/api/internal/supply-chain/consolidations/consolidations/', payload, () => mockCreateConsolidation(payload), 'supply.consolidation.create', 'new');
export const allocateConsolidationBoxes = (id, payload) => internal('post', `/api/internal/supply-chain/consolidations/consolidations/${id}/boxes/`, payload, () => mockConsolidationAction(id, 'allocate', payload), 'supply.consolidation.allocate', id);
export const consolidationAction = (id, action, payload) => internal('post', `/api/internal/supply-chain/consolidations/consolidations/${id}/actions/${action}/`, payload, () => mockConsolidationAction(id, action, payload), `supply.consolidation.${action}`, id);
export const consolidationAllocationAction = (id, allocationId, action, payload) => internal('post', `/api/internal/supply-chain/consolidations/consolidations/${id}/boxes/${allocationId}/actions/${action}/`, payload, () => mockConsolidationAction(id, action, payload), `supply.consolidation.${action}`, `${id}-${allocationId}`);

export const fetchShipments = (params = {}) => internal('get', '/api/internal/supply-chain/shipments/', params, () => mockFetchShipments(params), 'supply.shipment.view');
export const fetchShipment = (id) => internal('get', `/api/internal/supply-chain/shipments/${id}/`, undefined, () => mockFetchShipment(id), 'supply.shipment.view', id);
export const createShipment = (payload) => internal('post', '/api/internal/supply-chain/shipments/', payload, () => mockCreateShipment(payload), 'supply.shipment.create', 'new');
export const allocateShipmentBoxes = (id, payload) => internal('post', `/api/internal/supply-chain/shipments/${id}/boxes/`, payload, () => mockShipmentAction(id, 'allocate', payload), 'supply.shipment.allocate', id);
const SHIPMENT_ACTION_PATHS = { customs: 'customs-declare', dispatch: 'dispatch', 'port-arrival': 'port-arrival', 'warehouse-arrival': 'warehouse-arrival', clearance: 'warehouse-clearance', exception: 'exception', cancel: 'cancel' };
export const shipmentAction = (id, action, payload) => internal('post', `/api/internal/supply-chain/shipments/${id}/actions/${SHIPMENT_ACTION_PATHS[action] || action}/`, payload, () => mockShipmentAction(id, action, payload), `supply.shipment.${action}`, id);
