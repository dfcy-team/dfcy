import { describe, expect, it } from 'vitest';
import { buildBundleCreatePayload } from '../src/utils/bundleCreatePayload';

const base = {
  name: '组合', category: 8, season: '0', color: 'blue',
  legacySpuCode: 'OLD-SPU', legacySkuCode: 'OLD-SKU',
  components: [{ sku: 12, quantity: 2 }],
};

describe('组合商品创建请求', () => {
  it('新建 SPU 时不提交 existing_spu 字段', () => {
    const payload = buildBundleCreatePayload(base);
    expect(payload.spu_mode).toBe('new');
    expect(payload).not.toHaveProperty('existing_spu');
    expect(payload.components).toEqual([{ component_sku: 12, quantity: 2, cost_allocation_ratio: 1 }]);
  });

  it('复用 SPU 时提交选中的编号', () => {
    expect(buildBundleCreatePayload({ ...base, spuMode: 'existing', existingSpu: 42 }).existing_spu).toBe(42);
  });

  it('将组合规格传给服务端生成 SKU 编码', () => {
    expect(buildBundleCreatePayload({ ...base, specValues: { size: '180cm×240cm' } }).spec_values)
      .toEqual({ size: '180cm×240cm' });
    expect(buildBundleCreatePayload(base).spec_values).toEqual({});
  });
});
