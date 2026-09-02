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
    expect(page).toContain('category_node: form.category_node');
    expect(page).not.toContain('v-model="form.category"');
  });

  it('only presents active L3 leaf categories and displays their hierarchy path', () => {
    const page = read('src/views/development/DevelopmentProductArchiveList.vue');
    expect(page).toContain('Number(item.level) === 3');
    expect(page).toContain('item.is_active');
    expect(page).toContain('category.path');
    expect(page).toContain('category_path || row.category_name');
  });
});
