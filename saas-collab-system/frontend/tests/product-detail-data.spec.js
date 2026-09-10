import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductDetailData.vue'),
  'utf8'
);
const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/products.js'), 'utf8');

describe('商品明细数据页面契约', () => {
  it('使用分类树、服务端筛选和分页', () => {
    expect(page).toContain('分类目录');
    expect(page).toContain('categoryTree');
    expect(page).toContain('category_id: filters.category_id');
    expect(page).toContain('sku_status: filters.sku_status');
    expect(page).toContain('page: page.value');
    expect(page).toContain('@current-change="load"');
  });

  it('区分 SKU 商品名称、SPU 商品名称和转换状态', () => {
    expect(page).toContain('label="SKU商品名称"');
    expect(page).toContain('label="SPU商品名称"');
    expect(page).toContain('sku_product_name');
    expect(page).toContain('conversion_status_name');
    expect(page).toContain('row.sku_product_name || row.product_name');
  });

  it('提供查看、逐条调整生成、状态和删除操作', () => {
    expect(page).toContain('查看');
    expect(page).toContain('调整并生成');
    expect(page).toContain('toggleStatus(row)');
    expect(page).toContain('updateProductSkuStatus(row.sku_id, {');
    expect(page).toContain('deleteProductSku');
    expect(page).toContain('deleteProductLegacyItem');
    expect(page).toContain('can_deactivate');
    expect(page).toContain('存在业务引用');
    expect(page).toContain('启用（在售）');
    expect(page).toContain('停用（下架）');
  });

  it('显示导入阶段、耗时以及增量结果统计', () => {
    expect(page).toContain("'商品新增导入' : '旧商品档案导入'");
    expect(page).toContain('importStage');
    expect(page).toContain('importElapsed');
    expect(page).toContain('旧 SPU / SKU 编码可留空');
    expect(page).toContain('导入成功后自动生成 SPU / SKU');
    expect(page).toContain('importResult.created');
    expect(page).toContain('importResult.updated');
    expect(page).toContain('importResult.unchanged');
    expect(page).toContain('importResult.skipped');
    expect(api).toContain("url: dictionaryApi('legacy-items')");
    expect(api).toContain('timeout: 120000');
    expect(page).toContain('if (selectedRows.value.length)');
    expect(page).toContain('未选择记录，将修改全部匹配记录（含其他分页）');
    expect(page).toContain('ElMessageBox.confirm');
    expect(page).not.toContain(':disabled="!selectedRows.length"');
  });

  it('显示 SKU 物理和海关字段，并清晰处理空值', () => {
    expect(page).toContain('prop="package_weight"');
    expect(page).toContain('label="重量(g)"');
    expect(page).toContain('prop="package_volume"');
    expect(page).toContain('label="体积(m³)"');
    expect(page).toContain('prop="package_length_cm"');
    expect(page).toContain('prop="package_width_cm"');
    expect(page).toContain('prop="package_height_cm"');
    expect(page).toContain('label="原产国"');
    expect(page).toContain('label="HS编码"');
    expect(page).toContain('formatPhysical(row.package_weight, 3)');
    expect(page).toContain('formatPhysical(row.package_volume, 6)');
    expect(page).toContain("if (value === null || value === undefined || value === '') return '-'");
  });

  it('single and bulk edit expose all current SKU detail fields with explicit clearing', () => {
    const editableFields = [
      'package_weight',
      'package_volume',
      'package_length_cm',
      'package_width_cm',
      'package_height_cm',
      'origin_country',
      'hs_code',
    ];

    expect(page).toContain('const editableDetailFields = [');
    for (const field of editableFields) expect(page).toContain(`key: '${field}'`);

    expect(page).toContain('const editForm = reactive({');
    expect(page).toContain('const bulkForm = reactive({');
    expect(page).toContain('clearFields: []');
    expect(page).toContain('payload.clear_fields = [...new Set(editForm.clearFields)]');
    expect(page).toContain('clear_fields: [...new Set(bulkForm.clearFields)]');

    // Empty inputs are intentionally omitted; only an explicit clear checkbox
    // is allowed to send a clear_fields instruction to the API.
    expect(page).toContain("if (value !== '' && value !== null && value !== undefined) payload[field.key] = value;");
    expect(page).toContain("if (value !== '' && value !== null && value !== undefined) fields[field.key] = value;");
    expect(page).toContain('if (!Object.keys(payload).length && !payload.clear_fields?.length && !statusChanged)');
    expect(page).toContain('if (!Object.keys(payload.fields).length && !payload.clear_fields.length)');
  });

  it('按序号、选择、图片的顺序展示列，并保留放大预览', () => {
    const imageIndex = page.indexOf('<el-table-column label="图片"');
    const indexColumn = page.indexOf('<el-table-column type="index"');
    const selectionColumn = page.indexOf('<el-table-column v-if="canManage" type="selection"');
    expect(imageIndex).toBeGreaterThan(-1);
    expect(indexColumn).toBeLessThan(selectionColumn);
    expect(selectionColumn).toBeLessThan(imageIndex);
    expect(page).toContain('type="index" label="序号" width="70" fixed="left"');
    expect(page).toContain('type="selection" width="48" fixed="left"');
    expect(page).toContain('label="图片" width="92" align="center" fixed="left"');
    expect(page).toContain(':preview-src-list="[resolveImageUrl(row.image_url || row.image)]"');
    expect(page).toContain('preview-teleported');
  });

  it('首次加载缓存商品字典，翻页和筛选只重新请求明细列表', () => {
    const loadBody = page.slice(page.indexOf('async function load()'), page.indexOf('function applyProductDictionaries'));
    expect(page).toContain('getProductDictionaryCache(productDictionaryCacheScope');
    expect(page).toContain('cache.promise');
    expect(page).toContain('if (cache.promise === request) cache.promise = null;');
    expect(page).toContain('productDictionaryCacheScope(auth.currentUser)');
    expect(page).toContain('if (!currentProductDictionaryCache().value) void loadDictionaries();');
    expect(page).toContain('void Promise.all([loadDictionaries(), load()]);');
    expect(loadBody).not.toContain('await loadDictionaries()');
  });

  it('支持分类颜色失效刷新并提供独立导入模式', () => {
    expect(page).toContain('subscribeProductDictionaryCacheInvalidation');
    expect(page).toContain('fetchProductCategoryBackgroundColors()');
    expect(page).toContain('mergeCategoryBackgroundColors(');
    expect(page).toContain('data-testid="detail-io-menu"');
    expect(page).toContain('data-testid="legacy-import-mode"');
    expect(page).toContain('data-testid="legacy-import-button"');
    expect(page).toContain('command="legacy-import"');
    expect(page).toContain('value="auto"');
    expect(page).toContain('value="create"');
    expect(page).toContain('value="update"');
    expect(page).toContain('async function importLegacyFile(uploadedFile)');
    expect(page).toContain('importLegacyProductItems(normalizeImportHeaders(csvText), legacyImportMode.value)');
    expect(page).toContain("importLegacyProductItems(normalizedCsv, 'create')");
    expect(page).toContain('商品图片');
    expect(page).toContain('商品描述');
    expect(page).toContain('商品状态');
  });

  it('在商品明细页按选中的已生成 SKU 导出 BigSeller 商品表', () => {
    expect(page).toContain('data-testid="bigseller-create-product-export"');
    expect(page).toContain('下载 BigSeller 商品SKU表');
    expect(page).toContain(':disabled="!exportableSelectedRows.length || bigsellerExporting"');
    expect(page).toContain('selectedRows.value.filter((row) => row?.sku_code)');
    expect(page).toContain('downloadBigSellerProductWorkbook(exportableSelectedRows.value)');
    expect(page).not.toContain('组合商品导入');
  });

  it('在新增导入模板允许旧 SPU/SKU 留空，其他生成必需字段保留星号', () => {
    for (const header of ['旧SPU编码', '旧SKU编码', '*商品名称', '*完整类目编码', '*属性编码', '*颜色英文编码', '*规格']) {
      expect(page).toContain(`'${header}'`);
    }
    expect(page).toContain("value.replace(/^(\\uFEFF?)\\*/, '$1')");
    expect(page).toContain('data-testid="legacy-import-template"');
    expect(page).toContain('旧商品档案导入模板.csv');
  });

  it('商品新增导入后生成 SPU/SKU 并自动下载 BigSeller 表', () => {
    expect(page).toContain('command="create-import"');
    expect(page).toContain('title="商品新增导入"');
    expect(page).toContain('generateImportedProducts(normalizedCsv, rejectedLines, response.data?.created_ids || [])');
    expect(page).toContain('for (const id of createdIds)');
    expect(page).toContain('if (excludedLines.has(Number(target.line))) continue;');
    expect(page).toContain('generateLegacyProductItem(matched.id)');
    expect(page).toContain('downloadBigSellerProductWorkbook(generated.generatedRows, filename)');
    expect(page).toContain('BigSeller 表已自动下载');
    expect(page).toContain('importResult.bigseller_file_name');
  });
});
