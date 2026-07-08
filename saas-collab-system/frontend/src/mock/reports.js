import { successResponse } from './index';

export const mockBasicReports = () => successResponse({
  status: 'mock',
  module: 'reports.basic',
  items: [
    {
      report_no: 'MOCK-REPORT-001',
      report_name: 'Mock Basic Report',
      status: 'pending'
    }
  ]
});
