import { requestWithMockFallback } from './request';
import {
  mockBankReceipts,
  mockReconciliationExceptions,
  mockReconciliationMatchDetail,
  mockReconciliationMatches,
  mockStatements,
  mockWithdrawals
} from '../mock/financeReconciliation';

export const fetchPlatformStatements = () =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/statements/' }, mockStatements, 'finance.statements');

export const fetchWithdrawalRecords = () =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/withdrawals/' }, mockWithdrawals, 'finance.withdrawals');

export const fetchBankReceipts = () =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/bank-receipts/' }, mockBankReceipts, 'finance.bank_receipts');

export const fetchReconciliationMatches = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/reconciliation/matches/' },
    mockReconciliationMatches,
    'finance.reconciliation.matches'
  );

export const fetchReconciliationMatchDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/reconciliation/matches/', params: { id } },
    mockReconciliationMatchDetail,
    'finance.reconciliation.matches.detail'
  );

export const fetchReconciliationExceptions = () =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/reconciliation/exceptions/' },
    mockReconciliationExceptions,
    'finance.reconciliation.exceptions'
  );

export const runReconciliationMock = () =>
  requestWithMockFallback(
    { method: 'post', url: '/api/finance/reconciliation/run-mock/' },
    mockReconciliationMatchDetail,
    'finance.reconciliation.run_mock'
  );

export const confirmReconciliationMatch = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/finance/reconciliation/matches/${id}/confirm/` },
    mockReconciliationMatchDetail,
    'finance.reconciliation.matches.confirm'
  );

export const rejectReconciliationMatch = (id = 1) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/finance/reconciliation/matches/${id}/reject/` },
    mockReconciliationMatchDetail,
    'finance.reconciliation.matches.reject'
  );
