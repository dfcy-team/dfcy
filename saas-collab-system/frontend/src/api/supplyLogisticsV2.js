import { requestApi } from './request';
import { createIdempotencyKey } from './supplyChainV2';

const BASE = '/api/internal/supply-chain/v2/';
const enc = (id) => encodeURIComponent(id);
function write(method, url, data, key = createIdempotencyKey()) {
  return requestApi({ method, url, data, headers: { 'Idempotency-Key': key } });
}
export { createIdempotencyKey };
export const fetchDispatchOptions = (country_code) => requestApi({ method: 'get', url: `${BASE}dispatch-options/`, params: country_code ? { country_code } : {} });
export const fetchDispatchCandidates = (params = {}) => requestApi({ method: 'get', url: `${BASE}dispatch-candidates/`, params });
export const fetchDispatchBatches = (params = {}) => requestApi({ method: 'get', url: `${BASE}dispatch-batches/`, params });
export const createDispatchBatch = (data, key) => write('post', `${BASE}dispatch-batches/`, data, key);
export const fetchDispatchBatch = (id) => requestApi({ method: 'get', url: `${BASE}dispatch-batches/${enc(id)}/` });
export const updateDispatchBatch = (id, data, key) => write('patch', `${BASE}dispatch-batches/${enc(id)}/`, data, key);
export const advanceDispatchBatch = (id, data, key) => write('post', `${BASE}dispatch-batches/${enc(id)}/stage/`, data, key);
export const updateDispatchBatchMembers = (id, data, key) => write('post', `${BASE}dispatch-batches/${enc(id)}/members/`, data, key);
export const cancelDispatchBatch = (id, data, key) => write('post', `${BASE}dispatch-batches/${enc(id)}/cancel/`, data, key);
export const correctDispatchBatchDate = (id, data, key) => write('post', `${BASE}dispatch-batches/${enc(id)}/dates/`, data, key);
export const updateDispatchExpectedWarehouseDate = (id, data, key) => write('post', `${BASE}dispatch-batches/${enc(id)}/expected-warehouse-date/`, data, key);
export const generateInbound = (id, data, key) => write('post', `${BASE}dispatch-batches/${enc(id)}/inbound/`, data, key);
export const fetchInboundOrders = (params = {}) => requestApi({ method: 'get', url: `${BASE}inbound-orders/`, params });
export const fetchInboundOrder = (id) => requestApi({ method: 'get', url: `${BASE}inbound-orders/${enc(id)}/` });
export const updateInboundOrder = (id, data, key) => write('patch', `${BASE}inbound-orders/${enc(id)}/`, data, key);
export const confirmInboundOrder = (id, data, key) => write('post', `${BASE}inbound-orders/${enc(id)}/confirm/`, data, key);
export const fetchWmsReconciliation = (id) => requestApi({ method: 'get', url: `${BASE}inbound-orders/${enc(id)}/wms-reconciliation/` });
export const fetchWmsCandidates = (id, params) => requestApi({ method: 'get', url: `${BASE}inbound-orders/${enc(id)}/wms-candidates/`, params });
export const createWmsAllocation = (id, data, key) => write('post', `${BASE}inbound-orders/${enc(id)}/wms-allocations/`, data, key);
export const deactivateWmsAllocation = (id, allocationId, data, key) => write('post', `${BASE}inbound-orders/${enc(id)}/wms-allocations/${enc(allocationId)}/deactivate/`, data, key);
