import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.cwd(), 'src');
const page = fs.readFileSync(path.join(root, 'views/products/ProductMasterDetail.vue'), 'utf8');
const api = fs.readFileSync(path.join(root, 'api/products.js'), 'utf8');

describe('商品详情 SKU 编码生成契约', () => {
  it('仅向主数据管理权限展示生成按钮并保留冻结动作', () => {
    expect(page).toContain('生成SKU编码');
    expect(page).toContain("products.master.manage");
    expect(page).toContain('冻结编码');
  });

  it('提交颜色和动态规格到 SKU 创建 API', () => {
    expect(page).toContain('skuForm.color_code');
    expect(page).toContain('skuForm.spec_values');
    expect(page).toContain('createProductSku');
    expect(api).toContain("url: '/api/internal/products/skus/'");
  });
});
