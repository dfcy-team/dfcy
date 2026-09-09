import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');
const page = read('src/views/products/ProductBundleManager.vue');
const detailPage = read('src/views/products/ProductDetailData.vue');
const api = read('src/api/products.js');

describe('组合商品页面按钮与导入导出契约', () => {
  it('将组合商品导入导出归集到一个下拉菜单', () => {
    expect(page).toContain('data-testid="bundle-io-menu"');
    expect(page).toContain('导入与导出');
    expect(page).toContain('data-testid="bundle-import-template"');
    expect(page).toContain('下载组合商品导入模板');
    expect(page).toContain('data-testid="bundle-import-button"');
    expect(page).toContain('command="bundle-import"');
    expect(page).toContain('data-testid="bundle-import-file"');
    expect(page.indexOf('title="组合商品导入"')).toBeLessThan(page.indexOf('data-testid="bundle-import-template"'));
    expect(detailPage).not.toContain('组合商品导入');
  });

  it('保留新建入口并增加可选择的 BigSeller 组合表生成入口', () => {
    expect(page).toContain('data-testid="bundle-create-button"');
    expect(page).toContain('新建组合 SKU');
    expect(page).toContain('data-testid="bigseller-create-bundle-export"');
    expect(page).toContain('下载 BigSeller 组合商品SKU表');
    expect(page).toContain('@selection-change="selectedBundles = $event"');
    expect(page).toContain(':disabled="!selectedBundles.length || importing"');
    expect(page).toContain('downloadBigSellerBundleWorkbook(selectedBundles.value, skus.value, bundleComponents.value)');
  });

  it('批量导入复用现有创建链路，成功后自动生成 BigSeller 表', () => {
    expect(page).toContain('createProductSpu');
    expect(page).toContain('createProductSku');
    expect(page).toContain('createBundleComponent');
    expect(page).toContain('const result = await createBundle(prepareImportRow');
    expect(page).toContain('downloadBigSellerBundleWorkbook(createdSpus, createdSkus, createdComponents)');
    expect(page).toContain("'*组合商品名称', '*末级分类编码', '*季节编码', '*组合颜色英文编码'");
    expect(page).toContain('index <= 20');
    expect(api).toContain("url: dictionaryApi('bundle-components')");
    expect(api).toContain("'products.bundle_components'");
  });
});
