import { requestWithMockFallback } from './request';
import { salesManagementMocks } from '../mock/salesManagement';

const endpointByMode = {
  overview: '/api/internal/sales-management/overview/',
  orders: '/api/internal/sales-management/orders/',
  returns: '/api/internal/sales-management/returns/',
  stores: '/api/internal/sales-management/stores/',
  skus: '/api/internal/sales-management/skus/',
  exports: '/api/internal/sales-management/exports/',
  'data-quality': '/api/internal/sales-management/data-quality/'
};

export const fetchSalesPage = (mode, params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: endpointByMode[mode], params },
    () => salesManagementMocks[mode]?.(params),
    `sales_management.${mode}`
  );

export const fetchSalesOrderDetail = (id) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/sales-management/orders/${id}/` },
    () => salesManagementMocks.orderDetail?.(id),
    'sales_management.orders.detail'
  );

export const createSalesExport = (payload, idempotencyKey) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: '/api/internal/sales-management/exports/',
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey }
    },
    () => salesManagementMocks.createExport?.(payload),
    'sales_management.exports.create'
  );

export const requestSalesSyncRerun = (payload, idempotencyKey) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: '/api/internal/sales-management/sync-reruns/',
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey }
    },
    () => salesManagementMocks.requestRerun?.(payload),
    'sales_management.sync.rerun'
  );
