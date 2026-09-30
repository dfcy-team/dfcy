import { requestApi } from './request';
export const fetchReportDatasets = () => requestApi({ method: 'get', url: '/api/report/datasets/' });
export const queryReport = (config, signal) =>
  requestApi({ method: 'post', url: '/api/report/query/', data: config, signal, timeout: 30000 });
export const fetchSavedReportViews = () => requestApi({ method: 'get', url: '/api/report/views/' });
export const saveReportView = (payload, id) =>
  requestApi({ method: id ? 'put' : 'post', url: `/api/report/views/${id ? `${id}/` : ''}`, data: payload });
export const deleteReportView = (id) => requestApi({ method: 'delete', url: `/api/report/views/${id}/` });
