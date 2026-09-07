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
    expect(page).toContain('导入商品明细');
    expect(page).toContain('importStage');
    expect(page).toContain('importElapsed');
    expect(page).toContain('空白字段不会覆盖原值');
    expect(page).toContain('待生成商品不能填写商品状态');
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

  it('把图片列放在序号和选择列之前，并保留放大预览', () => {
    const imageIndex = page.indexOf('<el-table-column label="图片"');
    const indexColumn = page.indexOf('<el-table-column type="index"');
    const selectionColumn = page.indexOf('<el-table-column v-if="canManage" type="selection"');
    expect(imageIndex).toBeGreaterThan(-1);
    expect(imageIndex).toBeLessThan(indexColumn);
    expect(imageIndex).toBeLessThan(selectionColumn);
    expect(page).toContain(':preview-src-list="[resolveImageUrl(row.image_url || row.image)]"');
    expect(page).toContain('preview-teleported');
  });

  it('刷新查询时同步读取分类字典并支持三种导入模式', () => {
    expect(page).toContain('await loadDictionaries();');
    expect(page).toContain('data-testid="detail-import-mode"');
    expect(page).toContain('value="auto"');
    expect(page).toContain('value="create"');
    expect(page).toContain('value="update"');
    expect(page).toContain('importLegacyProductItems(csvText, importMode.value)');
    expect(page).toContain('商品图片');
    expect(page).toContain('商品描述');
    expect(page).toContain('商品状态');
  });
});
