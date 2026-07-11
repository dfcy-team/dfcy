import { successResponse } from './index';

export const mockStatements = () => successResponse({
  status: 'mock',
  module: 'finance.statements',
  items: [{ platform: 'mock-platform', statement_no: 'MOCK-ST-001', period_start: '2026-07-01', period_end: '2026-07-10', currency: 'USD', gross_amount: '1000.00', fee_amount: '80.00', net_amount: '920.00', status: 'pending' }]
});

export const mockWithdrawals = () => successResponse({
  status: 'mock',
  module: 'finance.withdrawals',
  items: [{ platform: 'mock-platform', withdrawal_no: 'MOCK-WD-001', requested_amount: '920.00', expected_amount: '920.00', completed_at: '', status: 'pending' }]
});

export const mockBankReceipts = () => successResponse({
  status: 'mock',
  module: 'finance.bank_receipts',
  items: [{ masked_account: '**** **** **** 1234', currency: 'USD', receipt_amount: '918.00', receipt_date: '2026-07-10', reference_no: 'MOCK-REF-001', status: 'unmatched' }]
});

const match = {
  id: 1,
  match_type: 'amount_date_rule',
  matched_amount: '918.00',
  difference_amount: '2.00',
  confidence: 0.81,
  status: 'review_required',
  reviewed_by_id: '',
  reviewed_by: '',
  reviewed_at: ''
};

export const mockReconciliationMatches = () => successResponse({
  status: 'mock',
  module: 'finance.reconciliation.matches',
  items: [match]
});

export const mockReconciliationMatchDetail = () => successResponse({
  status: 'mock',
  module: 'finance.reconciliation.matches.detail',
  ...match,
  audit_note: 'manual finance authorization required'
});

export const mockReconciliationExceptions = () => successResponse({
  status: 'mock',
  module: 'finance.reconciliation.exceptions',
  items: [{ exception_type: 'amount_difference', difference_amount: '2.00', status: 'assigned', assigned_to: 'finance-reviewer', resolution_note: 'placeholder only' }]
});
