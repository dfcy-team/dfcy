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
    expect(editor).toContain('店铺 SKU 匹配');
    expect(editor).toContain('仓库与库存');
    expect(editor).toContain('reserved_qty');
    expect(editor).toContain('available_qty');
    expect(editor).toContain('修改记录');
    expect(editor).toContain('internal_sku_id: route.params.id');
    expect(editor).toContain("object_type: 'ProductSKU'");
  });

  it('keeps immutable coding fields disabled and saves status separately', () => {
    expect(editor).toContain('SKU 编码、所属 SPU、颜色和规格生成后不可修改');
    expect(editor).toContain('updateProductSkuStatus');
    expect(editor).toContain('is_active: Boolean(form.is_active)');
  });

  it('preserves admin legacy-code editing while keeping alias history audit-backed', () => {
    expect(editor).toContain("auth.currentUser?.roles?.includes('administrator')");
    expect(editor).toContain('payload.legacy_sku_code');
    expect(editor).toContain(':disabled="!canEditLegacyCodes"');
    expect(masterList).toContain('payload.legacy_spu_code');
    expect(masterList).toContain('仅平台超级管理员或租户管理员可修改');
  });

  it('manages historical aliases through permission-gated add and close actions without editing history', () => {
    expect(editor).toContain("auth.hasPermission?.('products.master.manage')");
    expect(editor).toContain('fetchProductSkuAliases(route.params.id)');
    expect(editor).toContain('createProductSkuAlias(route.params.id');
    expect(editor).toContain('closeProductSkuAlias(route.params.id, closingAlias.value.id');
    expect(editor).toContain('version_no: closingAlias.value.version_no');
    expect(editor).toContain('结束别名生效期');
    expect(editor).not.toContain('deleteProductSkuAlias');
  });
});
