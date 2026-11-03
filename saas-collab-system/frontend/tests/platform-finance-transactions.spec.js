import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const page = readFileSync(join(process.cwd(), 'src/views/finance/PlatformStatementList.vue'), 'utf8');
const api = readFileSync(join(process.cwd(), 'src/api/financeReconciliation.js'), 'utf8');

describe('平台账单财务流水展示', () => {
  it('平台账单改用已验收财务汇总，不恢复已移除的旧页签', () => {
    expect(page).toContain('<FinanceSummary');
    expect(page).not.toContain('label="平台原始流水"');
    expect(page).not.toContain('label="结算核对"');
  });

  it('财务流水调用真实只读接口且支持筛选分页', () => {
    expect(api).toContain("url: '/api/finance/transactions/'");
    expect(api).toContain('requestApi');
    expect(api).toContain("url:'/api/finance/summary/'");
    expect(api).toContain('noMockFallback:true');
    expect(api).toContain('saveFinanceSummary');
  });
});
