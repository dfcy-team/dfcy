import { requestApi, downloadApiFile } from './request';
const base = '/api/internal/supply-chain/v2/dashboard/';
export const fetchDashboard = params => requestApi({ method: 'get', url: base, params });
export const fetchDashboardQueue = params => requestApi({ method: 'get', url: `${base}queue/`, params });
export const fetchMonthlyPayables = params => requestApi({ method: 'get', url: `${base}monthly/`, params });
export const downloadMonthlyPayables = params => {
  const query = new URLSearchParams({...params, export:'xlsx'});
  return downloadApiFile(`${base}monthly/?${query.toString()}`, `月度往来对账_${params.month||'当月'}.xlsx`);
};
