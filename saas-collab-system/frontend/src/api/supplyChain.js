import { requestWithMockFallback } from './request';
import {
  mockCreateSupplyOrder,
  mockFetchSupplyOrder,
  mockFetchSupplyOrders,
  mockRunSupplyOrderAction
} from '../mock/supplyChain';

const idempotencyKey = (action) =>
  `sc-f1-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

export const fetchSupplyOrders = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/purchasing/supply-orders/', params },
    () => mockFetchSupplyOrders(params),
    'supply.purchase-orders'
  );

export const fetchSupplyOrder = (id) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/purchasing/supply-orders/${id}/` },
    () => mockFetchSupplyOrder(id),
    'supply.purchase-order.detail'
  );

export const createSupplyOrder = (payload) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: '/api/internal/purchasing/supply-orders/',
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey('create') }
    },
    () => mockCreateSupplyOrder(payload),
    'supply.purchase-order.create'
  );

export const runSupplyOrderAction = (id, action, payload = {}) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/purchasing/supply-orders/${id}/actions/${action}/`,
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey(action) }
    },
    () => mockRunSupplyOrderAction(id, action, payload),
    `supply.purchase-order.${action}`
  );
