import { describe, expect, it } from 'vitest';
import { buildCostImportErrorCsv } from '../src/utils/costImportErrors';

describe('商品成本异常导出', () => {
  it('导出错误原因和源文件异常行的各列内容', () => {
    const csv = buildCostImportErrorCsv({
      error_batch_id: 13,
      source_headers: ['旧SKU编码', '确认成本', '调整原因'],
      error_rows: [{ row: 3098, values: ['missing-old-sku', '10.98', '待核对'] }],
      errors: [{ row: 3098, field: 'legacy_sku_code', message: '旧SKU编码在当前租户不存在。' }],
    });
    expect(csv).toContain('"异常批次","行号","字段","错误原因","旧SKU编码","确认成本","调整原因"');
    expect(csv).toContain('"13","3098","legacy_sku_code","旧SKU编码在当前租户不存在。","missing-old-sku","10.98","待核对"');
  });

  it('对可能被表格软件执行的公式内容作文本转义', () => {
    const csv = buildCostImportErrorCsv({
      source_headers: ['旧SKU编码'],
      error_rows: [{ row: 2, values: ['=HYPERLINK("x")'] }],
      errors: [{ row: 2, field: 'legacy_sku_code', message: 'unknown' }],
    });
    expect(csv).toContain('"\'=HYPERLINK(""x"")"');
  });
});
