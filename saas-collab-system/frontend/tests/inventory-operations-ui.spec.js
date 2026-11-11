import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
describe('inventory operations navigation and evidence contract', () => {
 const workbench = read('../src/views/inventory/InventoryWorkbench.vue');
 const decisions = read('../src/components/inventory/CountryInventoryDecisions.vue');
 const alerts = read('../src/views/inventory/InventoryAlertList.vue');
 it('defaults to authorized operations and nests legacy views under more analysis', () => {
  expect(workbench).toContain("auth.hasPermission('sales_management.skus.view') ? 'operations' : 'snapshot'");
  expect(workbench).toContain('更多分析'); expect(workbench).toContain("viewMode === 'summary'");
  expect(alerts).toContain('label="更多分析" name="analysis"');
  expect(alerts).toContain('label="评估状态" name="assessment"');
  expect(alerts).toContain('label="待核对数据" name="pending"');
 });
 it('keeps unknown statuses unasserted and exposes row evidence/actions', () => {
  expect(decisions).toContain('暂无销量数据');
  expect(decisions).toContain('暂无库存判断');
  expect(decisions).toContain("row.operations?.action || '数据待核实，暂不判断'");
  expect(decisions).toContain('row.operations?.evidence || []');
  expect(decisions).toContain('availability_history_unproven'); expect(decisions).toContain('顶部统计全部查询结果');
 });
});

