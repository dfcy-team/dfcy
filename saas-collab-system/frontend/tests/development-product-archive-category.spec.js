import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('development product archive category ownership', () => {
  it('uses the product category master data and submits a structured category id', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    expect(page).toContain('fetchProductCategories');
    expect(page).toContain('categoryOptions');
    expect(page).toContain('v-model="form.category_node"');
    expect(page).toContain('category_node: categoryId');
    expect(page).not.toContain('v-model="form.category"');
  });

  it('presents active L2/L3 categories and displays their hierarchy path', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    expect(page).toContain('[2, 3].includes(Number(item.level))');
    expect(page).toContain('item.is_active !== false');
    expect(page).toContain('category.path');
    expect(page).toContain('category_path || row.category_name');
    expect(page).toContain('请选择 L2 或 L3 分类');
  });
});
