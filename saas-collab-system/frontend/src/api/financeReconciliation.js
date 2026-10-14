import { requestApi } from './request';

export const fetchPlatformStatements = (params = {}) => requestApi({ method: 'get', url: '/api/finance/statements/', params });
export const fetchFinanceTransactions = (params = {}) => requestApi({ method: 'get', url: '/api/finance/transactions/', params });
export const fetchLazadaFinanceWide = (params = {}) => requestApi({ method: 'get', url: '/api/finance/lazada-income-wide/', params });
export const fetchWithdrawalRecords = (params = {}) => requestApi({ method: 'get', url: '/api/finance/withdrawals/', params });
export const fetchBankReceipts = (params = {}) => requestApi({ method: 'get', url: '/api/finance/bank-receipts/', params });
export const fetchReconciliationMatches = (params = {}) => requestApi({ method: 'get', url: '/api/finance/reconciliation/matches/', params });
export const fetchReconciliationMatchDetail = (id) => requestApi({ method: 'get', url: `/api/finance/reconciliation/matches/${id}/` });
export const fetchReconciliationExceptions = (params = {}) => requestApi({ method: 'get', url: '/api/finance/reconciliation/exceptions/', params });
export const createReconciliationMatch = (data) => requestApi({ method: 'post', url: '/api/finance/reconciliation/matches/', data });
export const confirmReconciliationMatch = (id) => requestApi({ method: 'post', url: `/api/finance/reconciliation/matches/${id}/confirm/` });
export const rejectReconciliationMatch = (id, reason) => requestApi({ method: 'post', url: `/api/finance/reconciliation/matches/${id}/reject/`, data: { reason } });
export const resolveReconciliationException = (id, reason) => requestApi({ method: 'post', url: `/api/finance/reconciliation/exceptions/${id}/resolve/`, data: { reason } });
