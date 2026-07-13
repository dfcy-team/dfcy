import { requestWithMockFallback } from './request';
import { mockReportExports } from '../mock/reportExports';

export const fetchReportExports = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/report/exports/', params },
    mockReportExports,
    'reports.exports'
  );
