import { requestApi, requestWithMockFallback } from './request';
import { mockReportExports } from '../mock/reportExports';

export const fetchReportExports = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/report/exports/', params },
    mockReportExports,
    'reports.exports'
  );

export const fetchReportCatalog = () => requestApi({ method: 'get', url: '/api/report/catalog/' });
export const createReportExport = (payload) => requestApi({ method: 'post', url: '/api/report/exports/', data: payload });
export const fetchReportExport = (id) => requestApi({ method: 'get', url: `/api/report/exports/${id}/` });
