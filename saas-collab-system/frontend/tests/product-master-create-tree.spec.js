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

  it('单个新增支持新建 SPU 或按新旧编码选择已有 SPU 新增 SKU', () => {
    expect(page).toContain('data-testid="standard-spu-mode"');
    expect(page).toContain('新建 SPU');
    expect(page).toContain('选择已有 SPU 新增 SKU');
    expect(page).toContain('搜索新/旧 SPU 编码或商品名称');
    expect(page).toContain('legacy_spu_code');
    expect(page).toContain('openSkuCreate(target)');
  });
});
