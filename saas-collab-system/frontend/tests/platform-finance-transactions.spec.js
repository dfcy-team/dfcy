import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const page = readFileSync(join(process.cwd(), 'src/views/finance/PlatformStatementList.vue'), 'utf8');
const api = readFileSync(join(process.cwd(), 'src/api/financeReconciliation.js'), 'utf8');

describe('平台账单财务流水展示', () => {
  it('默认展示真实财务流水并保留账单汇总页签', () => {
    expect(page).toContain("const activeTab = ref('transactions')");
    expect(page).toContain('label="财务流水"');
    expect(page).toContain('label="账单汇总"');
    expect(page).toContain('prop="signed_amount"');
    expect(page).toContain('prop="match_status"');
  });

  it('财务流水调用真实只读接口且支持筛选分页', () => {
    expect(api).toContain("url: '/api/finance/transactions/'");
    expect(api).toContain('requestApi');
    expect(page).toContain('period_start:');
    expect(page).toContain('external_order_id:');
    expect(page).toContain('v-model:current-page="pagination.page"');
  });
});
