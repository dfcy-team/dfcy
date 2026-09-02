import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.cwd(), 'src');
const page = fs.readFileSync(path.join(root, 'views/products/ProductMasterList.vue'), 'utf8');
const api = fs.readFileSync(path.join(root, 'api/products.js'), 'utf8');

describe('商品主数据创建与分类目录契约', () => {
  it('显示分类目录树、筛选输入和受权限控制的创建按钮', () => {
    expect(page).toContain('分类目录');
    expect(page).toContain('<el-tree');
    expect(page).toContain('categoryFilter');
    expect(page).toContain("products.master.manage");
    expect(page).toContain('创建商品');
  });

  it('调用商品 SPU 创建 API 并提交末级分类', () => {
    expect(api).toContain("url: '/api/internal/products/spus/'");
    expect(page).toContain('createProductSpu');
    expect(page).toContain('category_node: createForm.category_node');
  });
});
