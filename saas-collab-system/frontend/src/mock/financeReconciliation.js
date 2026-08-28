import { successResponse } from './index';

const page = (module, results) => ({
  api_status: 'mock', module, count: results.length, next: null, previous: null, results
});

export const mockStatements = () => successResponse(page('finance.statements', [
  { platform: 'mock-platform', statement_no: 'MOCK-ST-001', period_start: '2026-07-01', period_end: '2026-07-10', currency: 'USD', gross_amount: '1000.00', fee_amount: '80.00', net_amount: '920.00', status: 'imported' }
]));

export const mockWithdrawals = () => successResponse(page('finance.withdrawals', [
  { platform: 'mock-platform', withdrawal_no: 'MOCK-WD-001', currency: 'USD', requested_amount: '920.00', expected_amount: '920.00', completed_at: '', status: 'requested' }
]));

export const mockBankReceipts = () => successResponse(page('finance.bank_receipts', [
  { masked_account: '****1234', currency: 'USD', receipt_amount: '918.00', receipt_date: '2026-07-10', reference_no: 'MOCK-REF-001', status: 'imported' }
]));

const match = {
  id: 1,
  match_type: 'amount_date_rule',
  matched_amount: '918.00',
  difference_amount: '2.00',
  confidence: 0.81,
  status: 'suggested',
  reviewed_by_id: '',
  reviewed_by: '',
  reviewed_at: ''
};

export const mockReconciliationMatches = () => successResponse(page('finance.reconciliation.matches', [match]));

export const mockReconciliationMatchDetail = () => successResponse({
  status: 'mock',
  module: 'finance.reconciliation.matches.detail',
  ...match,
  audit_note: 'manual finance authorization required'
});

export const mockReconciliationExceptions = () => successResponse(page('finance.reconciliation.exceptions', [
  { id: 1, exception_type: 'amount_difference', difference_amount: '2.00', status: 'open', assigned_to: null, resolution_note: '' }
]));
