import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductMasterList.vue'),
  'utf8'
);

describe('商品主数据 SPU-SKU 关联契约', () => {
  it('使用 SPU 响应中的 sku_codes，避免用截断的 SKU 列表拼接关联', () => {
    expect(page).toContain('Array.isArray(spu.sku_codes)');
    expect(page).toContain(".join('、')");
    expect(page).not.toContain('fetchProductSkuList');
    expect(page).not.toContain('page_size: 1000');
  });
});
