import { successResponse } from './index';

const metrics = {
  supplier_id: 10001,
  supplier_name: 'Mock Supplier',
  period: '2026-07',
  total_tasks: 20,
  on_time_tasks: 16,
  overdue_tasks: 2,
  exception_tasks: 1,
  total_shipments: 18,
  accurate_shipments: 17,
  feedback_on_time_count: 15,
  on_time_rate: 0.8,
  overdue_rate: 0.1,
  exception_rate: 0.05,
  shipment_accuracy_rate: 0.94,
  feedback_timeliness_rate: 0.75,
  total_score: 86,
  rule_version: 'mock-v1'
};

export const mockSupplierPerformanceList = () => successResponse({ status: 'mock', module: 'suppliers.performance', items: [metrics] });
export const mockSupplierPerformanceDetail = () => successResponse({ status: 'mock', module: 'suppliers.performance.detail', ...metrics });
export const mockMySupplierPerformance = () => successResponse({ status: 'mock', module: 'suppliers.my_performance', ...metrics });
export const mockMySupplierPerformanceHistory = () => successResponse({ status: 'mock', module: 'suppliers.my_performance.history', items: [metrics] });
