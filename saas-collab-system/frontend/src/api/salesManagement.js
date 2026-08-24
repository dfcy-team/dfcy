import { requestWithMockFallback } from './request';
import { salesManagementMocks } from '../mock/salesManagement';

const endpointByMode = {
  overview: '/api/internal/commerce/overview/',
  orders: '/api/internal/commerce/orders/',
  returns: '/api/internal/commerce/refunds/',
  stores: '/api/internal/commerce/sales/stores/',
  skus: '/api/internal/commerce/sales/skus/',
  exports: '/api/internal/sales-management/exports/',
  'data-quality': '/api/internal/commerce/quality/'
};

const mockModeByMode = { returns: 'refunds', 'data-quality': 'data-quality' };

const mockFor = (mode, params = {}) => {
  const handler = salesManagementMocks[mockModeByMode[mode] || mode];
  return typeof handler === 'function' ? () => handler(params) : undefined;
};

const salesRequest = (config, mockHandler, moduleName) =>
  requestWithMockFallback(config, mockHandler, moduleName);

export const fetchSalesFilters = (params = {}) =>
  salesRequest(
    { method: 'get', url: '/api/internal/commerce/filters/', params },
    mockFor('filters', params),
    'sales_management.filters'
  );

export const fetchSalesPage = (mode, params = {}) => {
  const url = endpointByMode[mode];
  if (!url) {
    return Promise.resolve({
      success: false,
      code: 'SALES_MODE_NOT_SUPPORTED',
      message: `销售管理页面模式未配置：${mode}`,
      data: null
    });
  }
  return salesRequest(
    { method: 'get', url, params },
    mockFor(mode, params),
    `sales_management.${mode}`
  );
};

export const fetchSalesOrderDetail = (id) =>
  salesRequest(
    { method: 'get', url: `/api/internal/commerce/orders/${id}/` },
    salesManagementMocks.orderDetail ? () => salesManagementMocks.orderDetail(id) : undefined,
    'sales_management.orders.detail'
  );

export const createSalesExport = (payload, idempotencyKey) =>
  salesRequest(
    {
      method: 'post',
      url: '/api/internal/sales-management/exports/',
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey }
    },
    salesManagementMocks.createExport ? () => salesManagementMocks.createExport(payload) : undefined,
    'sales_management.exports.create'
  );
