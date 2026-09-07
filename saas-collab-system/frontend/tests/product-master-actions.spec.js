import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');
const page = read('src/views/products/ProductMasterList.vue');
const api = read('src/api/products.js');

describe('商品主数据删除与状态动作契约', () => {
  it('提供删除按钮并将引用冲突转为停用', () => {
    expect(page).toContain('data-testid="product-master-status-button"');
    expect(page).toContain('data-testid="`product-master-delete-${row.id}`"');
    expect(page).toContain('deleteMaster(row)');
    expect(page).toContain('STATE_CONFLICT');
    expect(page).toContain('can_deactivate');
    expect(page).toContain('referenceDescription(response)');
    expect(page).toContain("lifecycle_status: 'discontinued'");
    expect(page).toContain("sales_status: 'stopped'");
  });

  it('通过专用状态接口提交生命周期和销售状态', () => {
    expect(page).toContain('openStatusEdit(row)');
    expect(page).toContain('saveStatus');
    expect(page).toContain('updateProductSpuStatus(statusForm.id');
    expect(page).toContain('lifecycle_status: statusForm.lifecycle_status');
    expect(page).toContain('sales_status: statusForm.sales_status');
    expect(api).toContain("url: `/api/internal/products/spus/${id}/status/`");
    expect(api).toContain("url: `/api/internal/products/spus/${id}/`");
  });

  it('保留 SKU 与旧商品删除和状态接口，并支持旧命名兼容', () => {
    expect(api).toContain("url: `/api/internal/products/skus/${id}/`");
    expect(api).toContain("url: `/api/internal/products/skus/${id}/status/`");
    expect(api).toContain("url: `${dictionaryApi('legacy-items')}${id}/`");
    expect(api).toContain('deleteProductLegacyItem = deleteLegacyProductItem');
  });
});
