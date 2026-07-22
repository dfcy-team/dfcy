import { createIdempotencyKey, requestWithMockFallback } from './request';
import {
  mockBankReceipts,
  mockReconciliationExceptions,
  mockReconciliationMatchDetail,
  mockReconciliationMatches,
  mockStatements,
  mockWithdrawals
} from '../mock/financeReconciliation';

export const fetchPlatformStatements = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/statements/', params }, mockStatements, 'finance.statements');

export const fetchWithdrawalRecords = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/withdrawals/', params }, mockWithdrawals, 'finance.withdrawals');

export const fetchBankReceipts = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/bank-receipts/', params }, mockBankReceipts, 'finance.bank_receipts');

export const fetchReconciliationMatches = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/reconciliation/matches/', params },
    mockReconciliationMatches,
    'finance.reconciliation.matches'
  );

export const fetchReconciliationMatchDetail = (id = 1) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/finance/reconciliation/matches/${id}/` },
    mockReconciliationMatchDetail,
    'finance.reconciliation.matches.detail'
  );

export const fetchReconciliationExceptions = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/reconciliation/exceptions/', params },
    mockReconciliationExceptions,
    'finance.reconciliation.exceptions'
  );

export const runReconciliationMock = (payload = { platform: 'mock', currency: 'USD' }) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: '/api/finance/reconciliation/run-mock/',
      data: payload,
      headers: { 'Idempotency-Key': createIdempotencyKey('finance-reconcile') }
    },
    mockReconciliationMatchDetail,
    'finance.reconciliation.run_mock'
  );

export const confirmReconciliationMatch = (id = 1, payload = {}) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/finance/reconciliation/matches/${id}/confirm/`, data: payload },
    mockReconciliationMatchDetail,
    'finance.reconciliation.matches.confirm'
  );

export const rejectReconciliationMatch = (id = 1, payload = {}) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/finance/reconciliation/matches/${id}/reject/`, data: payload },
    mockReconciliationMatchDetail,
    'finance.reconciliation.matches.reject'
  );

export const resolveReconciliationException = (id, payload) =>
  requestWithMockFallback(
    { method: 'post', url: `/api/finance/reconciliation/exceptions/${id}/resolve/`, data: payload },
    mockReconciliationExceptions,
    'finance.reconciliation.exceptions.resolve'
  );
