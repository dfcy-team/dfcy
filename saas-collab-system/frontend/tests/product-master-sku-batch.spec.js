import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  buildSkuBatchPayload,
  normalizeBatchSelection,
  skuBatchCombinationCount,
} from '../src/utils/skuBatch';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductMasterList.vue'),
  'utf8',
);
const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/products.js'), 'utf8');

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

  it('显示多选控件、组合数量和 200 条限制，并调用批量接口', () => {
    expect(page).toContain('data-testid="batch-color"');
    expect(page).toContain('`batch-spec-${dimension.code}`');
    expect(page).toContain('data-testid="batch-submit"');
    expect(page).toContain('multiple');
    expect(page).toContain('allow-create');
    expect(page).toContain('skuBatchCombinationCount');
    expect(page).toContain('skuBatchLimit = 200');
    expect(page).toContain('createProductSkuBatch(payload)');
    expect(page).toContain('skuGenerationErrorMessage(response)');
    expect(page).toContain('skuGenerationErrorMessage(error?.response || error)');
    expect(api).toContain("url: '/api/internal/products/skus/batch/'");
    expect(api).toContain('color_codes');
    expect(api).toContain('spec_values');
  });

  it('从批量响应 data 顶层读取 created/skipped，不被 results 首项解包覆盖', () => {
    const batchResponse = {
      data: {
        created: 6,
        skipped: 0,
        total: 6,
        results: [{ sku_code: 'SKU-1', created: 1 }],
      },
    };
    const result = batchResponse.data || {};

    expect(Number(result.created || 0)).toBe(6);
    expect(Number(result.skipped || 0)).toBe(0);
    expect(page).toContain('const result = response.data || {};');
    expect(page).not.toContain('const result = detailData(response.data);');
  });
});
