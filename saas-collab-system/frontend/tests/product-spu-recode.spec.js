import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(path.resolve(process.cwd(), 'src/views/products/ProductMasterList.vue'), 'utf8');
const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/products.js'), 'utf8');

describe('商品主数据 SPU 受控重编码契约', () => {
  it('展示旧SPU列并按商品状态控制修改入口', () => {
    expect(page).toContain('label="旧SPU"');
    expect(page).toContain('row.legacy_spu_code');
    expect(page).toContain('data-testid="product-master-recode-button"');
    expect(page).toContain("row.lifecycle_status || 'draft'");
    expect(page).toContain("row.sales_status || 'not_listed'");
    expect(page).toContain('row.is_code_frozen');
  });

  it('单条和CSV均先预检再显式执行', () => {
    expect(page).toContain('data-testid="recode-preview"');
    expect(page).toContain('data-testid="recode-csv-preview"');
    expect(page).toContain('data-testid="recode-execute"');
    expect(page).toContain('dry_run: true, atomic: true, rows');
    expect(page).toContain('dry_run: false, atomic: true, rows');
    expect(page).toContain('source_spu_code,product_name,attribute_code,serial_number');
    expect(page).toContain('data-testid="recode-product-name"');
    expect(api).toContain("url: '/api/internal/products/spus/recode/'");
  });

  it('逐行显示来源、目标、状态、冲突字段和SKU映射', () => {
    expect(page).toContain('data-testid="recode-results"');
    expect(page).toContain('prop="row_number"');
    expect(page).toContain('prop="source_spu_code"');
    expect(page).toContain('prop="target_spu_code"');
    expect(page).toContain('row.conflicts?.length');
    expect(page).toContain('conflict.code');
    expect(page).toContain('conflict.message');
    expect(page).toContain('conflict.field');
    expect(page).toContain('row.sku_mappings || []');
    expect(page).toContain('hasRecodeConflicts');
  });
});
