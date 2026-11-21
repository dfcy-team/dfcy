// @vitest-environment jsdom
import { mount, flushPromises } from '@vue/test-utils';
import { reactive } from 'vue';
import { beforeEach, expect, it, vi } from 'vitest';
import { ElButton, ElTable, ElTableColumn } from 'element-plus';
import Category from '../src/views/inventory/CategoryInventory.vue';

const mocks = vi.hoisted(() => ({ auth: null, request: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => mocks.auth }));
vi.mock('../src/api/request', () => ({ requestApi: mocks.request }));

beforeEach(() => {
  mocks.auth = reactive({ currentUser: { id: 1, tenant_id: 1 }, authorizationStale: false });
  mocks.request.mockReset();
  mocks.request.mockResolvedValue({ success: true, data: { countries: [], results: [], count: 0 } });
});
const mountPage = (options = {}) => mount(Category, { ...options, global: { components: { ElButton, ElTable, ElTableColumn }, ...options.global } });

it('routes the unmapped sentinel to a paginated unmapped query, not an SPU query', async () => {
  const wrapper = mountPage();
  await flushPromises();
  const vm = wrapper.vm.$.setupState;
  vm.country = 7;
  vm.applied = { country_id: 7, days: 30, search: '' };
  vm.enter({ id: -1, name: '未映射商品库存' });
  await flushPromises();
  mocks.request.mockResolvedValueOnce({ success: true, data: { level: 'unmapped', count: 1, results: [{ id: 4, source_sku: 'SRC-4', seller_sku: 'SELL-4', warehouse__name: '仓库 A', on_hand_qty: 8, available_qty: 5 }] } });
  await vm.changePage(1);
  await flushPromises();

  const call = mocks.request.mock.calls.at(-1)[0];
  expect(call.params).toMatchObject({ country_id: 7, category_id: -1, level: 'unmapped', offset: 0 });
  expect(call.params.spu_id).toBeUndefined();
  expect(wrapper.text()).toContain('SRC-4');
  expect(wrapper.text()).toContain('SELL-4');
  expect(wrapper.text()).toContain('仓库 A');
  expect(wrapper.text()).not.toContain('店铺销售');
  expect(wrapper.text()).not.toContain('仓库库存</');
  expect(wrapper.find('.el-table').text()).not.toContain('ABC 等级');
  expect(wrapper.find('.el-table').text()).not.toContain('规格数');
  vm.changePage(2);
  await flushPromises();
  expect(mocks.request.mock.calls.at(-1)[0].params).toMatchObject({ level: 'unmapped', category_id: -1, offset: 20 });
  wrapper.unmount();
});

it('retains cloud variants and toggles their inline detail panel', async () => {
  const wrapper = mountPage();
  await flushPromises();
  const vm = wrapper.vm.$.setupState;
  vm.country = 7;
  vm.applied = { country_id: 7, days: 30, search: '', warehouse_id: 4, category_ids: '2' };
  const row = { id: 31, name: '帽子', sku_count: 1, variants: [{ id: 91, name: '帽子', code: 'SKU-91', specification: '蓝色' }] };
  vm.rows = [row];
  vm.level = 'spu';
  await flushPromises();
  const expand = wrapper.findAll('button').find(button => button.text().includes('展开 1 个规格'));
  expect(expand).toBeTruthy();
  await expand.trigger('click');
  await flushPromises();
  expect(vm.expandedVariants.has(31)).toBe(true);
  expect(wrapper.text()).toContain('SKU-91');
  expect(wrapper.text()).toContain('蓝色');
  const detail = wrapper.findAll('button').filter(button => button.text() === '店铺销售').at(-1);
  expect(detail).toBeTruthy();
  await detail.trigger('click');
  await flushPromises();
  const call = mocks.request.mock.calls.at(-1)[0];
  expect(call.params).toMatchObject({ country_id: 7, warehouse_id: 4, category_ids: '2', level: 'stores', sku_id: 91 });
  expect(call.params.spu_id).toBeUndefined();
  expect(call.params.days).toBe(30);
  wrapper.unmount();
});

it('uses the cloud embedded title', () => {
  const wrapper = mountPage({ props: { embedded: true } });
  expect(wrapper.text()).toContain('仓库库存明细');
  expect(wrapper.text()).not.toContain('仓库库存明细查询');
  wrapper.unmount();
});
