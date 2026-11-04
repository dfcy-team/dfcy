import { requestApi, fetchApiFile } from './request';
export const fetchFinanceLedger = (params = {}) => requestApi({ method: 'get', url: '/api/finance/ledger/', params, noMockFallback: true });

export const fetchPlatformStatements = (params = {}) => requestApi({ method: 'get', url: '/api/finance/statements/', params });
export const fetchFinanceTransactions = (params = {}) => requestApi({ method: 'get', url: '/api/finance/transactions/', params });
export const fetchLazadaFinanceWide = (params = {}) => requestApi({ method: 'get', url: '/api/finance/lazada-income-wide/', params });
export const fetchWithdrawalRecords = (params = {}) => requestApi({ method: 'get', url: '/api/finance/withdrawals/', params });
export const fetchPlatformWallet = () => requestApi({ method: 'get', url: '/api/finance/platform-wallet/overview/', noMockFallback: true });
export const fetchApiWithdrawals = (params = {}) => requestApi({ method: 'get', url: '/api/finance/platform-wallet/withdrawals/', params, noMockFallback: true });
export const syncPlatformWallet = () => requestApi({ method: 'post', url: '/api/finance/platform-wallet/sync/', data: {}, noMockFallback: true });
export const saveWalletSchedule = (data) => requestApi({ method: 'post', url: '/api/finance/platform-wallet/schedule/', data, noMockFallback: true });
export const fetchBankReceipts = (params = {}) => requestApi({ method: 'get', url: '/api/finance/bank-receipts/', params });
export const fetchReconciliationMatches = (params = {}) => requestApi({ method: 'get', url: '/api/finance/reconciliation/matches/', params });
export const fetchReconciliationMatchDetail = (id) => requestApi({ method: 'get', url: `/api/finance/reconciliation/matches/${id}/` });
export const fetchReconciliationExceptions = (params = {}) => requestApi({ method: 'get', url: '/api/finance/reconciliation/exceptions/', params });
export const createReconciliationMatch = (data) => requestApi({ method: 'post', url: '/api/finance/reconciliation/matches/', data });
export const confirmReconciliationMatch = (id) => requestApi({ method: 'post', url: `/api/finance/reconciliation/matches/${id}/confirm/` });
export const rejectReconciliationMatch = (id, reason) => requestApi({ method: 'post', url: `/api/finance/reconciliation/matches/${id}/reject/`, data: { reason } });
export const resolveReconciliationException = (id, reason) => requestApi({ method: 'post', url: `/api/finance/reconciliation/exceptions/${id}/resolve/`, data: { reason } });

export const fetchFinanceSummary = (params = {}) => requestApi({ method:'get', url:'/api/finance/summary/', params, noMockFallback:true, timeout:120000 });
export const fetchFinanceSummaryJob = (id) => requestApi({ method:'get', url:`/api/finance/summary/jobs/${id}/`, noMockFallback:true });
export const rebuildFinanceSummary = (id, revision) => requestApi({ method:'post', url:'/api/finance/summary/'+id+'/rebuild/', data:{revision}, noMockFallback:true, timeout:180000 });
export const fetchFinanceSummaryDocument = (id) => fetchApiFile(`/api/finance/summary/${id}/document/`);
export const saveFinanceSummary = (id, data) => requestApi({ method:'post', url:`/api/finance/summary/${id}/settings/`, data, noMockFallback:true, timeout:120000 });
export const fetchFinanceSummaryTable = (id, params) => requestApi({ method:'get', url:`/api/finance/summary/${id}/table/`, params, noMockFallback:true, timeout:120000 });
export const fetchFinanceSummaryDetail = (id, params) => requestApi({ method:'get', url:`/api/finance/summary/${id}/table-detail/`, params, noMockFallback:true, timeout:120000 });
export const saveFinanceSummaryFee = (id, data) => requestApi({ method:'post', url:`/api/finance/summary/${id}/fee/`, data, noMockFallback:true, timeout:120000 });
export const fetchFinanceSummaryHistory = (id, params) => requestApi({ method:'get', url:`/api/finance/summary/${id}/history/`, params, noMockFallback:true, timeout:120000 });
