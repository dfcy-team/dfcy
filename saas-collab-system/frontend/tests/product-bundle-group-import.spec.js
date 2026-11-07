import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchProductCategories, fetchProductColors, fetchProductAttributes, fetchProductSkuList, createProductBundle, downloadBigSellerBundleWorkbook } = vi.hoisted(() => ({
  fetchProductCategories: vi.fn(), fetchProductColors: vi.fn(), fetchProductAttributes: vi.fn(), fetchProductSkuList: vi.fn(), createProductBundle: vi.fn(), downloadBigSellerBundleWorkbook: vi.fn(),
}));
vi.mock('../src/api/products', () => ({
  fetchProductCategories, fetchProductColors, fetchProductAttributes, fetchProductSkuList, createProductBundle,
  fetchProductMasterList: vi.fn(), fetchBundleComponents: vi.fn(), fetchProductBundleAvailability: vi.fn(), fetchProductBundleDetail: vi.fn(),
  previewProductBundleMigration: vi.fn(), confirmProductBundleMigration: vi.fn(), uploadProductSkuImage: vi.fn(), cacheProductBundleImage: vi.fn(), updateProductBundle: vi.fn(),
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('../src/utils/bigsellerWorkbook', () => ({ downloadWorkbook: vi.fn(), downloadBigSellerBundleWorkbook }));
vi.mock('read-excel-file', () => ({ default: vi.fn() }));

import ProductBundleManager from '../src/views/products/ProductBundleManager.vue';

const headers = ['旧SPU编码', '旧SKU编码', '*组合商品名称', '*末级分类编码', '*属性编码', '*组合颜色英文编码', 'SPU分组标识', '*单品SKU1', '*SKU1数量'];
const row = (name, category = '10101', season = '0', group = '') => ['', '', name, category, season, 'white', group, 'NORMAL-1', '1'];
const file = (records) => ({ name: 'group.csv', arrayBuffer: async () => new TextEncoder().encode(records.map((cells) => cells.join(',')).join('\n')).buffer });

function createdResult(index, category = 3, season = '0') {
  return { success: true, data: { spu: { id: index, category_node: category, season_code: season }, sku: { id: index + 100, sku_code: `B-${index}` }, components: [] } };
}

async function runImport(records) {
  const wrapper = mount(ProductBundleManager, { props: { importOnly: true }, global: { stubs: true } });
  await flushPromises();
  const state = wrapper.vm.$.setupState;
  await state.importBundleFile(file([headers, ...records]));
  await flushPromises();
  const result = { calls: createProductBundle.mock.calls.map(([payload]) => payload), summary: state.importSummary };
  wrapper.unmount();
  return result;
}

describe('组合商品导入 SPU 分组 mounted 回归', () => {
  beforeEach(() => {
    fetchProductCategories.mockReset().mockResolvedValue({ success: true, data: [
      { id: 1, level: 1, code: '1', is_active: true }, { id: 2, level: 2, code: '01', parent: 1, is_active: true }, { id: 3, level: 3, code: '01', parent: 2, is_active: true },
      { id: 4, level: 1, code: '2', is_active: true }, { id: 5, level: 2, code: '01', parent: 4, is_active: true }, { id: 6, level: 3, code: '01', parent: 5, is_active: true },
    ] });
    fetchProductColors.mockReset().mockResolvedValue({ success: true, data: [{ code: 'white', is_active: true }] });
    fetchProductAttributes.mockReset().mockResolvedValue({ success: true, data: [{ code: 'S', is_active: true }] });
    fetchProductSkuList.mockReset().mockResolvedValue({ success: true, data: [{ id: 9, sku_code: 'NORMAL-1', is_active: true, product_type: 'normal' }] });
    createProductBundle.mockReset().mockImplementation((payload) => Promise.resolve(createdResult(createProductBundle.mock.calls.length, payload.category_node, payload.season_code)));
    downloadBigSellerBundleWorkbook.mockClear();
  });

  it('同组复用SPU，不同组独立创建，空分组逐行创建', async () => {
    const { calls, summary } = await runImport([row('同组一', '10101', '0', 'A'), row('同组二', '10101', '0', 'A'), row('另一组', '10101', '0', 'B'), row('空组一'), row('空组二')]);
    expect(calls).toHaveLength(5);
    expect(calls.map((call) => call.spu_mode)).toEqual(['new', 'existing', 'new', 'new', 'new']);
    expect(calls[1].existing_spu).toBe(1);
    expect(calls[2].existing_spu).toBeUndefined();
    expect(summary.created).toBe(5);
  });

  it('拒绝分组内分类或属性冲突', async () => {
    const { calls, summary } = await runImport([row('组一', '10101', '0', 'A'), row('分类冲突', '20101', '0', 'A'), row('属性冲突', '10101', 'S', 'A')]);
    expect(calls).toHaveLength(1);
    expect(summary.errors).toHaveLength(2);
    expect(summary.errors.map((error) => error.message).join(' ')).toContain('分类或属性编码');
  });

  it('禁止旧SPU编码与分组标识同时填写', async () => {
    const conflicting = ['OLD', '', ...row('互斥', '10101', '0', 'A').slice(2)];
    const { calls, summary } = await runImport([conflicting]);
    expect(calls).toHaveLength(0);
    expect(summary.errors[0].message).toContain('不能同时填写');
  });

  it('首行失败不会将分组键写入映射，后续有效行可创建并复用', async () => {
    createProductBundle.mockImplementationOnce(() => Promise.resolve({ success: false, http_status: 400, code: 'VALIDATION_ERROR', message: '首行服务端拒绝' }));
    const { calls, summary } = await runImport([row('先失败', '10101', '0', 'A'), row('有效一', '10101', '0', 'A'), row('有效二', '10101', '0', 'A')]);
    expect(calls).toHaveLength(3);
    expect(calls[0].spu_mode).toBe('new');
    expect(calls[1].spu_mode).toBe('new');
    expect(calls[2]).toMatchObject({ spu_mode: 'existing', existing_spu: 2 });
    expect(summary.errors).toHaveLength(1);
    expect(summary.created).toBe(2);
  });

  it.each([
    ['网络结果不确定', { success: false, http_status: null, code: 'HTTP_NETWORK_ERROR', message: 'network timeout' }],
    ['服务端5xx', { success: false, http_status: 503, code: 'HTTP_ERROR', message: 'server error' }],
    ['成功响应缺少SPU ID', { success: true, data: { spu: { category_node: 3, season_code: '0' }, sku: { id: 100, sku_code: 'B-1' }, components: [] } }],
  ])('%s 后阻止同组再次创建并继续处理其他分组', async (_label, firstResponse) => {
    createProductBundle.mockImplementationOnce(() => Promise.resolve(firstResponse));
    const { calls, summary } = await runImport([
      row('首个不确定结果', '10101', '0', 'A'), row('同组不重试', '10101', '0', 'A'), row('其他组继续', '10101', '0', 'B'),
    ]);
    expect(calls).toHaveLength(2);
    expect(calls.map(({ spu_mode }) => spu_mode)).toEqual(['new', 'new']);
    expect(summary.created).toBe(1);
    expect(summary.errors.length).toBeGreaterThanOrEqual(2);
  });
});
