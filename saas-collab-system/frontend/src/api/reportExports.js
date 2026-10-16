import { downloadApiFile, requestApi, requestWithMockFallback, useMock } from './request';
import { mockReportExports } from '../mock/reportExports';

export const fetchReportExports = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/report/exports/', params },
    mockReportExports,
    'reports.exports'
  );

export const fetchReportCatalog = () => requestApi({ method: 'get', url: '/api/report/catalog/' });
export const fetchReportExportJobs = () => requestApi({ method: 'get', url: '/api/report/export-jobs/', timeout: 10000 });
export const createReportExport = (payload) => useMock
  ? Promise.resolve({ success: false, code: 'MOCK_WRITE_DISABLED', message: 'Mock模式不创建导出申请。', data: null })
  : requestApi({ method: 'post', url: '/api/report/exports/', data: payload });
export const createReportExportJob = (payload) => useMock
  ? Promise.resolve({ success: false, code: 'MOCK_WRITE_DISABLED', message: 'Mock模式不创建后台导出任务。', data: null })
  : requestApi({ method: 'post', url: '/api/report/export-jobs/', data: payload, timeout: 10000 });
export const fetchReportExportJob = (id) => requestApi({ method: 'get', url: `/api/report/export-jobs/${encodeURIComponent(id)}/`, timeout: 8000 });
export const cancelReportExportJob = (id) => requestApi({ method: 'delete', url: `/api/report/export-jobs/${encodeURIComponent(id)}/`, timeout: 8000 });
export const fetchReportExport = (id) => requestApi({ method: 'get', url: `/api/report/exports/${id}/` });
export const downloadReportExport = (id) => useMock
  ? Promise.resolve({ success: false, code: 'MOCK_WRITE_DISABLED', message: 'Mock模式不生成下载凭证。', data: null })
  : requestApi({ method: 'post', url: `/api/report/exports/${id}/download/`, data: {} });
export const downloadReportFile = (reference, filename) => {
  if (typeof reference !== 'string' || !reference.startsWith('/api/report/exports/')) {
    return Promise.resolve({ success: false, code: 'INVALID_DOWNLOAD_REFERENCE', message: '下载引用无效。', data: null });
  }
  return downloadApiFile(reference, filename);
};
