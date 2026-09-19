import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  SKU_VARIANT_MODES,
  buildSkuCombinations,
  buildSkuBatchPayload,
  calculatePackageVolume,
  normalizeBatchSelection,
  skuBatchCombinationCount,
} from '../src/utils/skuBatch';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductMasterList.vue'),
  'utf8',
);
const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/products.js'), 'utf8');
const dialog = fs.readFileSync(
  path.resolve(process.cwd(), 'src/components/products/SkuGenerationDialog.vue'),
  'utf8',
);

describe('商品主数据批量生成 SKU', () => {
  it('计算颜色和规格维度的笛卡尔组合，未选维度按一个默认值计算', () => {
    expect(skuBatchCombinationCount(['white', 'blue'], { size: ['180cm', '200cm', '220cm'] })).toBe(6);
    expect(skuBatchCombinationCount(['white', 'blue'], { size: [] })).toBe(2);
    expect(skuBatchCombinationCount([], { size: ['180cm'] })).toBe(0);
  });

  it('去重并生成后端约定的批量请求体，空规格不会覆盖默认值', () => {
    expect(normalizeBatchSelection([' white ', 'white', '', 'blue'])).toEqual(['white', 'blue']);
    expect(buildSkuBatchPayload(7, ['white', 'blue', 'white'], {
      size: ['180cm', '200cm'],
      material: [],
    })).toEqual({
      spu: 7,
      color_codes: ['white', 'blue'],
      spec_values: { size: ['180cm', '200cm'] },
    });
  });

  it('显示四模式、组合矩阵和明细预览，并调用批量接口', () => {
    expect(page).toContain('<SkuGenerationDialog');
    expect(dialog).toContain('data-testid="batch-color"');
    expect(dialog).toContain('data-testid="sku-variant-mode"');
    expect(dialog).toContain('data-testid="sku-combination-matrix"');
    expect(dialog).toContain('data-testid="batch-submit"');
    expect(dialog).toContain('有颜色有规格');
    expect(dialog).toContain('无颜色无规格');
    expect(dialog).toContain('const batchLimit = 200');
    expect(dialog).toContain('createProductSkuBatch(requestBase(selectedCombinations.value, true))');
    expect(dialog).toContain('downloadBigSellerProductWorkbook(created');
    expect(api).toContain("url: '/api/internal/products/skus/batch/'");
    expect(api).toContain('uploadProductSkuImage');
  });

  it('生成四种编码模式所需的组合，并正确换算体积', () => {
    const dimensions = [{ code: 'size' }];
    expect(buildSkuCombinations(SKU_VARIANT_MODES.COLOR_SPEC, ['BLUE'], dimensions, { size: ['15M'] })).toHaveLength(1);
    expect(buildSkuCombinations(SKU_VARIANT_MODES.COLOR_ONLY, ['BLUE'], dimensions, { size: ['15M'] })[0].spec_values).toEqual({});
    expect(buildSkuCombinations(SKU_VARIANT_MODES.SPEC_ONLY, ['BLUE'], dimensions, { size: ['15M'] })[0].color_code).toBe('');
    expect(buildSkuCombinations(SKU_VARIANT_MODES.SINGLE, ['BLUE'], dimensions, { size: ['15M'] })).toEqual([
      expect.objectContaining({ color_code: '', spec_values: {} }),
    ]);
    expect(calculatePackageVolume(150, 200, 20)).toBe('0.600000');
  });
});
