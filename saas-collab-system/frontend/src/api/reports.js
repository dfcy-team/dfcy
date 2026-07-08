import { getMockResponse } from './request';
import { mockBasicReports } from '../mock/reports';

export const fetchBasicReports = () => getMockResponse(mockBasicReports, 'reports.basic');
