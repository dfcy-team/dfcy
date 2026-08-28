import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { mockBankReceipts, mockStatements } from '../src/mock/financeReconciliation';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('sales, inventory and finance module contract', () => {
  it('keeps finance calls inside the finance partition', () => {
    const source = read('src/api/financeReconciliation.js');
    expect(source).toContain('/api/finance/statements/');
    expect(source).toContain('/api/finance/reconciliation/matches/${id}/');
    expect(source).toContain('/api/finance/reconciliation/exceptions/${id}/resolve/');
    expect(source).not.toMatch(/\/api\/(internal|external|rpa)\/|\/admin\//);
  });

  it('uses pagination, query filters and an idempotency key', () => {
    const page = read('src/components/Phase2DataPage.vue');
    const api = read('src/api/financeReconciliation.js');
    expect(page).toContain('<el-pagination');
    expect(page).toContain('page_size: pageSize.value');
    expect(api).toContain("'Idempotency-Key': createIdempotencyKey('finance-reconcile')");
  });

  it('keeps inventory alert reads on the Mock/API switch', () => {
    const alerts = read('src/api/alerts.js');
    expect(alerts).toContain('mockInventoryAlerts');
    expect(alerts).toContain("'alerts.inventory'");
    expect(read('src/mock/alerts.js')).toContain("alert_id: 'DEMO-INV-002'");
  });

  it('gates reconciliation and exception actions independently', () => {
    expect(read('src/views/finance/ReconciliationMatchDetail.vue')).toContain("permission: 'finance.reconcile'");
    expect(read('src/views/finance/ReconciliationExceptionList.vue')).toContain("permission: 'finance.exception.handle'");
  });

  it('keeps synthetic module access read-only', () => {
    const authMock = read('src/mock/auth.js');
    expect(authMock).toContain("'alerts.view'");
    expect(authMock).toContain("'replenishment.view'");
    expect(authMock).not.toContain("'finance.reconcile'");
    expect(authMock).not.toContain("'finance.exception.handle'");
  });

  it('keeps synthetic finance mocks paginated and account data masked', () => {
    const statements = mockStatements();
    const receipts = mockBankReceipts();
    expect(statements.data).toMatchObject({ count: 1, next: null, previous: null });
    expect(Array.isArray(statements.data.results)).toBe(true);
    expect(receipts.data.results[0].masked_account).toMatch(/^\*+/);
    expect(JSON.stringify(receipts)).not.toContain('demo-account');
  });

  it('does not expose fund execution or real platform integration', () => {
    const files = [
      'src/api/financeReconciliation.js',
      'src/views/finance/ReconciliationMatchList.vue',
      'src/views/finance/ReconciliationMatchDetail.vue',
      'src/views/finance/ReconciliationExceptionList.vue'
    ].map(read).join('\n');
    expect(files).not.toMatch(/submitPayment|transferFunds|withdrawFunds|BigSeller|Shopee|TikTok/);
  });
});
