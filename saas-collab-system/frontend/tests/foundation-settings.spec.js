import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  canAccessPath,
  findRouteCapability,
  menuItems,
} from '../src/router/menu';
import {
  categoryBackgroundColor,
  categoryRowClass,
  categoryRowStyle,
  defaultCategoryBackgroundColor,
} from '../src/utils/productCategoryPresentation';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

const foundationMenu = menuItems.find((item) => item.label === '基础档案');
const internalUser = (permissions) => ({
  user_type: 'internal',
  is_superuser: false,
  permissions,
});

describe('基础档案设置前端契约', () => {
  it('only appends one permissioned settings child to the foundation menu', () => {
    expect(foundationMenu).toBeTruthy();
    expect(foundationMenu.permissions).toEqual([
      'masterdata.view',
      'listings.product_detail.view',
      'integrations.store_mapping.view',
      'integrations.product_mapping.view',
      'products.master.view',
      'products.category.view',
      'products.attribute.view',
      'products.color.view',
      'products.specification.view',
      'products.bundle.view',
      'masterdata.settings.view',
    ]);
    expect(foundationMenu.children.map((item) => item.path)).toEqual([
      '/products/master',
      '/products/details',
      '/products/platform-details',
      '/products/categories',
      '/products/attributes',
      '/products/colors',
      '/products/specifications',
      '/products/bundles',
      '/master-data/platforms',
      '/master-data/sites',
      '/master-data/stores',
      '/master-data/warehouses',
      '/master-data/suppliers',
      '/master-data/settings',
    ]);
    expect(foundationMenu.children.at(-1)).toEqual({
      path: '/master-data/settings',
      label: '基础档案设置',
      permissions: ['masterdata.settings.view'],
    });
  });

  it('registers a lazy route with the same view permission and denies other users', () => {
    const router = read('src/router/index.js');
    expect(router).toContain("const FoundationSettings = () => import('../views/masterdata/FoundationSettings.vue');");
    expect(router).toMatch(/\{ path: 'master-data\/settings', component: FoundationSettings \}/);

    expect(findRouteCapability('/master-data/settings')).toMatchObject({
      path: '/master-data/settings',
      permissions: ['masterdata.settings.view'],
      userTypes: ['internal'],
    });
    expect(canAccessPath(internalUser(['masterdata.settings.view']), '/master-data/settings')).toBe(true);
    expect(canAccessPath(internalUser([]), '/master-data/settings')).toBe(false);
    expect(canAccessPath({ user_type: 'external', permissions: ['masterdata.settings.view'] }, '/master-data/settings')).toBe(false);
  });

  it('exposes the color editor, preview, reset, save and manage gate', () => {
    const page = read('src/views/masterdata/FoundationSettings.vue');
    const api = read('src/api/products.js');
    expect(page).toContain('商品分类背景颜色');
    expect(page).toContain('el-color-picker');
    expect(page).toContain('颜色预览');
    expect(page).toContain('恢复默认');
    expect(page).toContain('保存设置');
    expect(page).toContain("auth.hasPermission('masterdata.settings.manage')");
    expect(page).toContain('row_background_color');
    expect(page).toContain('category_id: row.id');
    expect(api).toContain('fetchProductCategoryBackgroundColors');
    expect(api).toContain('updateProductCategoryBackgroundColors');
  });

  it('keeps the old palette when no custom color exists and prioritizes a custom L2 color', () => {
    const categories = [
      { id: 10, level: 1, code: '1', name: '家居' },
      { id: 20, parent: 10, level: 2, code: '01', name: '卧室', row_background_color: '#AABBCC' },
      { id: 30, parent: 20, level: 3, code: '01', name: '床品' },
      { id: 40, parent: 10, level: 2, code: '02', name: '厨房' },
    ];
    expect(categoryBackgroundColor({ category_node: 30 }, categories)).toBe('#AABBCC');
    expect(categoryRowClass({ category_node: 30 }, categories)).toBe('product-category-custom');
    expect(categoryRowStyle({ category_node: 30 }, categories)).toEqual({
      '--product-category-row-background': '#AABBCC',
    });

    const fallback = defaultCategoryBackgroundColor(categories[3]);
    expect(fallback).toBeTruthy();
    expect(categoryBackgroundColor({ category_node: 40 }, categories)).toBe(fallback);
    expect(categoryRowClass({ category_node: 40 }, categories)).toMatch(/^product-category-tone-(warm|[0-4])$/);
    expect(categoryRowStyle({ category_node: 40 }, categories)).toEqual({});
  });

  it('wires custom row styles into both product tables without removing default classes', () => {
    const master = read('src/views/products/ProductMasterList.vue');
    const detail = read('src/views/products/ProductDetailData.vue');
    for (const page of [master, detail]) {
      expect(page).toContain(':row-class-name="productRowClassName"');
      expect(page).toContain(':row-style="productRowStyle"');
      expect(page).toContain('categoryRowStyle');
      expect(page).toContain('product-category-custom');
      expect(page).toContain('--product-category-row-background');
    }
  });
});
