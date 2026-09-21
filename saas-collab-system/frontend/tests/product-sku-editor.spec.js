import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const editor = readFileSync(resolve('src/views/products/ProductSkuEditor.vue'), 'utf8');
const detailList = readFileSync(resolve('src/views/products/ProductDetailData.vue'), 'utf8');
const router = readFileSync(resolve('src/router/index.js'), 'utf8');
const masterList = readFileSync(resolve('src/views/products/ProductMasterList.vue'), 'utf8');

describe('single SKU editor', () => {
  it('opens generated SKUs in the dedicated editor route', () => {
    expect(detailList).toContain("router.push(`/products/details/${row.sku_id}/edit`)");
    expect(router).toContain("path: 'products/details/:id/edit'");
  });

  it('contains the accepted mapping, inventory and audit workspaces', () => {
    expect(editor).toContain('平台 SKU 映射');
    expect(editor).toContain('仓库与库存');
    expect(editor).toContain('修改记录');
    expect(editor).toContain('internal_sku_id: route.params.id');
    expect(editor).toContain("object_type: 'ProductSKU'");
  });

  it('keeps immutable coding fields disabled and saves status separately', () => {
    expect(editor).toContain('SKU 编码、所属 SPU、颜色和规格生成后不可修改');
    expect(editor).toContain('updateProductSkuStatus');
    expect(editor).toContain('is_active: Boolean(form.is_active)');
  });

  it('allows only platform or tenant administrators to submit legacy codes', () => {
    expect(editor).toContain("auth.currentUser?.roles?.includes('administrator')");
    expect(editor).toContain('payload.legacy_sku_code');
    expect(editor).toContain(':disabled="!canEditLegacyCodes"');
    expect(masterList).toContain('payload.legacy_spu_code');
    expect(masterList).toContain('仅平台超级管理员或租户管理员可修改');
  });
});
