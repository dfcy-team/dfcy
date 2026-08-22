import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { buildCategoryTree, categoryRowClass } from '../src/utils/productCategoryPresentation';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');
const master = read('src/views/products/ProductMasterList.vue');
const detail = read('src/views/products/ProductDetailData.vue');
const platform = read('src/views/masterdata/PlatformProductDetailList.vue');
const productsApi = read('src/api/products.js');

describe('基础档案商品列表增强契约', () => {
  it('分类树统一展示分类编号并让三级分类继承二级色彩', () => {
    const tree = buildCategoryTree([
      { id: 1, level: 1, code: '01', name: '家纺布艺' },
      { id: 2, parent: 1, level: 2, code: '01', name: '床上用品' },
      { id: 3, parent: 2, level: 3, code: '01', name: '床笠' },
    ]);
    expect(tree[0].displayName).toBe('01 家纺布艺');
    expect(tree[0].children[0].displayName).toBe('01 床上用品');
    expect(categoryRowClass({ category_node: 3 }, [
      { id: 2, parent: 1, level: 2, code: '01', name: '床上用品' },
      { id: 3, parent: 2, level: 3, code: '01', name: '床笠' },
    ])).toBe('product-category-tone-warm');
    expect(master).toContain(":props=\"{ label: 'displayName', children: 'children' }\"");
    expect(detail).toContain(":props=\"{ label: 'displayName', children: 'children' }\"");
  });

  it('三张业务表第一列使用跨页序号，勾选列排在序号之后', () => {
    expect(master).toContain(':index="(page - 1) * pageSize + 1"');
    expect(detail).toContain(':index="(page - 1) * pageSize + 1"');
    expect(platform).toContain(':index="(filters.page - 1) * filters.page_size + 1"');
    expect(master.indexOf('type="index"')).toBeLessThan(master.indexOf('type="selection"'));
    expect(detail.indexOf('type="index"')).toBeLessThan(detail.indexOf('type="selection"'));
    expect(platform.indexOf('type="index"')).toBeLessThan(platform.indexOf('type="selection"'));
  });

  it('主数据提供勾选后的批量修改和移动目录操作', () => {
    expect(master).toContain('@selection-change="selectedMasterRows = $event"');
    expect(master).toContain('openBulkMasterEdit');
    expect(master).toContain('openMoveCategory');
    expect(master).toContain('bulkUpdateProductSpus({ ids, fields });');
    expect(master).toContain("operation: 'move_category'");
    expect(productsApi).toContain("/api/internal/products/spus/bulk-update/");
  });

  it('商品明细提供缩略图预览、CSV 批量缓存和逐行结果', () => {
    expect(detail).toContain('label="图片"');
    expect(detail).toContain('preview-src-list');
    expect(detail).toContain('批量导入图片');
    expect(detail).toContain('旧 SKU 编码和新 SKU 编码至少填写一个');
    expect(detail).toContain('downloadImageBatchTemplate');
    expect(detail).toContain('bulkCacheProductImages({');
    expect(detail).toContain('cached_url');
    expect(detail).toContain("['updated', 'unchanged'].includes(resultStatus)");
    expect(detail).toContain("updated: '已更新'");
    expect(detail).toContain("unchanged: '无变化'");
    expect(productsApi).toContain('/api/internal/products/details/images/bulk-cache/');
  });
});
