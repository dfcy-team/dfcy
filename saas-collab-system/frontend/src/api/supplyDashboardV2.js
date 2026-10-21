import { requestApi } from './request';
const base = '/api/internal/supply-chain/v2/dashboard/';
export const fetchDashboard = params => requestApi({ method: 'get', url: base, params });
export const fetchDashboardQueue = params => requestApi({ method: 'get', url: `${base}queue/`, params });
