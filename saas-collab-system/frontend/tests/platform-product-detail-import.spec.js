import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/views/masterdata/PlatformProductDetailList.vue'),
  'utf8',
);

describe('platform product detail import affordances', () => {
  it('exposes a downloadable CSV template and field guidance', () => {
    expect(pageSource).toContain('下载导入模板');
    expect(pageSource).toContain('字段说明');
    expect(pageSource).toContain('平台商品明细导入模板.csv');
    expect(pageSource).toContain("const templateHeaders = [");
    expect(pageSource).toContain("'国家代码'");
    expect(pageSource).toContain('prop="country_code" label="国家代码"');
    expect(pageSource).not.toMatch(/templateHeaders\s*=\s*\[[\s\S]*?'站点'/);
    expect(pageSource).toContain("'变体ID'");
    expect(pageSource).toContain("'旧SKU编码'");
  });

  it('keeps the upload contract restricted to CSV/XLSX', () => {
    expect(pageSource).toContain('accept=".csv,.xlsx"');
    expect(pageSource).toContain("importPlatformProductDetails(file, { dryRun: false })");
  });
});
