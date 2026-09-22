import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const detailList = readFileSync(resolve('src/views/products/ProductDetailData.vue'), 'utf8');
const editor = readFileSync(resolve('src/views/products/ProductBundleEditor.vue'), 'utf8');
const router = readFileSync(resolve('src/router/index.js'), 'utf8');

describe('bundle product editor separation', () => {
  it('routes bundle and standard SKUs to different editor pages', () => {
    expect(detailList).toContain("row.product_type === 'bundle'");
    expect(detailList).toContain('router.push(`/products/bundles/${row.sku_id}/edit`)');
    expect(detailList).toContain('router.push(`/products/details/${row.sku_id}/edit`)');
    expect(router).toContain("path: 'products/bundles/:id/edit'");
  });

  it('shows bundle-specific composition, calculated stock and version workspaces', () => {
    expect(editor).toContain('组合内容');
    expect(editor).toContain('组合库存');
    expect(editor).toContain('版本与修改记录');
    expect(editor).toContain('fetchProductBundleAvailability');
    expect(editor).toContain('updateProductBundle');
  });

  it('retains platform mappings and protects relationship changes with audit fields', () => {
    expect(editor).toContain('平台 SKU 映射');
    expect(editor).toContain('internal_sku_id: route.params.id');
    expect(editor).toContain('修改组合内容时必须填写变更原因和生效时间');
  });
});
