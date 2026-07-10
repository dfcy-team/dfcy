import { requestWithMockFallback } from './request';
import { mockBasicReports } from '../mock/reports';

export const fetchBasicReports = () =>
  requestWithMockFallback({ method: 'get', url: '/api/report/basic/' }, mockBasicReports, 'reports.basic');
