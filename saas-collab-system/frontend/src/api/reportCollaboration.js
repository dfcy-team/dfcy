import { requestApi } from './request';
export const createReportException = payload => requestApi({ method: 'post', url: '/api/report/exceptions/', data: payload });
export const fetchReportExceptionSource = id => requestApi({ method: 'get', url: `/api/report/exceptions/${id}/source/` });
export const fetchReportViewHistory = id => requestApi({ method: 'get', url: `/api/report/views/${id}/history/` });
