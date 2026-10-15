import { requestApi } from './request';

const base = '/api/internal/supply-chain/v2/warehouses/';

export function createSupplyWarehouseIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `warehouse-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export const fetchSupplyWarehouses = (params = {}) => requestApi({ method: 'get', url: base, params });
export const fetchSupplyWarehouseOptions = () => requestApi({ method: 'get', url: '/api/internal/supply-chain/v2/warehouse-options/' });
export const createSupplyWarehouse = (data, idempotencyKey = createSupplyWarehouseIdempotencyKey()) => requestApi({
  method: 'post', url: base, data, headers: { 'Idempotency-Key': idempotencyKey },
});
export const updateSupplyWarehouse = (id, data, idempotencyKey = createSupplyWarehouseIdempotencyKey()) => requestApi({
  method: 'patch', url: `${base}${id}/`, data, headers: { 'Idempotency-Key': idempotencyKey },
});
