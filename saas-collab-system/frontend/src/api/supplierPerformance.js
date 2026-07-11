import { requestWithMockFallback } from './request';
import {
  mockMySupplierPerformance,
  mockMySupplierPerformanceHistory,
  mockSupplierPerformanceDetail,
  mockSupplierPerformanceList
} from '../mock/supplierPerformance';

export const fetchSupplierPerformance = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/suppliers/performance/' },
    mockSupplierPerformanceList,
    'suppliers.performance'
  );

export const fetchSupplierPerformanceDetail = (supplierId = 10001) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/suppliers/performance/${supplierId}/` },
    mockSupplierPerformanceDetail,
    'suppliers.performance.detail'
  );

export const calculateSupplierPerformanceMock = () =>
  requestWithMockFallback(
    { method: 'post', url: '/api/internal/suppliers/performance/calculate-mock/' },
    mockSupplierPerformanceList,
    'suppliers.performance.calculate_mock'
  );

export const fetchMySupplierPerformance = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/external/supplier/performance/' },
    mockMySupplierPerformance,
    'suppliers.my_performance'
  );

export const fetchMySupplierPerformanceHistory = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/external/supplier/performance/history/' },
    mockMySupplierPerformanceHistory,
    'suppliers.my_performance.history'
  );
