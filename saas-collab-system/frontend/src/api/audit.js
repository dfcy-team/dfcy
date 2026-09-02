import { downloadApiFile, requestWithMockFallback, useMock } from './request';
import { mockOperationLogs } from '../mock/audit';

const mockOperationLogDetail = (id) => {
  const response = mockOperationLogs();
  const rows = response?.data?.items || [];
  const item = rows.find((row) => String(row.id || '') === String(id)) || rows[0] || {};
  return {
    ...response,
    data: {
      ...item,
      id: item.id || id,
      before_data: {},
      after_data: {}
    }
  };
};

const queryString = (params = {}) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value);
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : '';
};

export const fetchOperationLogs = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/audit/operation-logs/', params },
    mockOperationLogs,
    'audit.operation_logs'
  );

export const fetchOperationLog = (id) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/audit/operation-logs/${id}/` },
    () => mockOperationLogDetail(id),
    'audit.operation_logs.detail'
  );

export const exportOperationLogs = (params = {}) => {
  if (useMock) {
    return Promise.resolve({
      success: true,
      code: 'OK',
      message: '演示导出已生成。',
      data: { api_status: 'mock' }
    });
  }
  return downloadApiFile(
    `/api/internal/audit/operation-logs/export/${queryString(params)}`,
    'operation-logs.csv'
  );
};
