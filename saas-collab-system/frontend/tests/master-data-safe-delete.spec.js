import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('基础档案安全删除契约', () => {
  it('只在适用的五类档案页接入删除操作', () => {
    for (const page of [
      'PlatformMasterList.vue',
      'CountrySiteMasterList.vue',
      'StoreMasterList.vue',
      'WarehouseMasterList.vue',
      'SupplierMasterList.vue'
    ]) {
      expect(read(`src/views/masterdata/${page}`), page).toContain(':delete-handler');
    }

    for (const page of [
      'src/views/products/ProductMasterList.vue',
      'src/views/products/ProductDetailData.vue',
      'src/views/masterdata/PlatformProductDetailList.vue',
      'src/views/masterdata/FoundationSettings.vue'
    ]) {
      expect(read(page), page).not.toContain(':delete-handler');
    }
  });

  it('通过租户档案接口删除并对关联冲突给出停用提示', () => {
    const api = read('src/api/masterData.js');
    const page = read('src/components/AdminResourcePage.vue');

    expect(api).toContain("method: 'delete'");
    expect(api).toContain('/api/internal/master-data/${resource}/${id}/');
    expect(page).toContain('v-if="deleteHandler && manageAccess.visible"');
    expect(page).toContain('仅在无关联数据时允许删除，有关联数据请先停用');
    expect(page).toContain("response?.http_status === 409 || response?.code === 'STATE_CONFLICT'");
    expect(page).toContain("error === 'cancel' || error === 'close'");
  });
});
