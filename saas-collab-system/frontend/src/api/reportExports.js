import { downloadApiFile, requestApi, requestWithMockFallback, useMock } from './request';
import { mockReportExports } from '../mock/reportExports';

export const fetchReportExports = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/report/exports/', params },
    mockReportExports,
    'reports.exports'
  );

export const fetchReportCatalog = () => requestApi({ method: 'get', url: '/api/report/catalog/' });
export const createReportExport = (payload) => useMock
  ? Promise.resolve({ success: false, code: 'MOCK_WRITE_DISABLED', message: 'Mock模式不创建导出申请。', data: null })
  : requestApi({ method: 'post', url: '/api/report/exports/', data: payload });
export const fetchReportExport = (id) => requestApi({ method: 'get', url: `/api/report/exports/${id}/` });
export const downloadReportExport = async (id, fileFormat = 'csv') => {
  if (useMock) return { success: false, code: 'MOCK_WRITE_DISABLED', message: 'Mock模式不生成下载凭证。', data: null };
  const grant = await requestApi({ method: 'post', url: `/api/report/exports/${id}/download/`, data: {} });
  if (!grant.success) return grant;
  if (grant.data.placeholder_only) return grant;
  return downloadApiFile(grant.data.download_reference, `sales-details-${id}.${fileFormat}`);
};
