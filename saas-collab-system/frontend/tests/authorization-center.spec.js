import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { authorizationSummary, authorizationQuery } from '../src/utils/authorizationCenter';
import Center from '../src/views/integrations/AuthorizationCenter.vue';

const mocks = vi.hoisted(() => ({ permissions: [], stores: vi.fn(), warehouses: vi.fn(), storeDetail: vi.fn(), warehouseDetail: vi.fn(), capabilities: vi.fn(), subjects: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ get currentUser() { return { user_type: 'internal', permissions: mocks.permissions }; }, hasPermission: code => mocks.permissions.includes(code) }) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('../src/api/request', () => ({ useMock: true }));
vi.mock('../src/api/integrations', () => ({ fetchStoreAuthorizations: mocks.stores, fetchWarehouseAuthorizations: mocks.warehouses, fetchStoreAuthorizationDetail: mocks.storeDetail, fetchWarehouseAuthorizationDetail: mocks.warehouseDetail, fetchConnectionCapabilities: mocks.capabilities, fetchAuthorizationSubjectCandidates: mocks.subjects }));
const success = results => ({ success: true, data: { count: results.length, results } });
const store = { id: 1, store_id: 10, store_name: '测试店铺', platform: 'shopee', expires_at: '2027-01-01T00:00:00Z' };
const warehouse = { id: 2, warehouse_id: 20, warehouse_name: '测试仓库', provider: 'jifeng_wms', oauth_expires_at: '2027-02-01T00:00:00Z' };
// Test page contracts independently of ElSelect's jsdom popup measurement loop.
// The real selector and dialogs are also checked in the local browser.
const create = () => mount(Center, { global: { plugins: [ElementPlus], stubs: {
  teleport: true,
  ElSelect: { props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>' },
  ElOption: { props: ['value', 'label'], template: '<option :value="value">{{ label }}</option>' }
} } });
const click = async (wrapper, label) => { await wrapper.findAll('button').find(button => button.text() === label).trigger('click'); await flushPromises(); };

beforeEach(() => {
  vi.clearAllMocks(); mocks.permissions = ['integrations.store.view', 'integrations.warehouse.view'];
  mocks.stores.mockResolvedValue(success([store])); mocks.warehouses.mockResolvedValue(success([warehouse]));
  mocks.storeDetail.mockResolvedValue({ success: true, data: store });
  mocks.warehouseDetail.mockResolvedValue({ success: true, data: warehouse });
  mocks.capabilities.mockResolvedValue({ success: true, data: { results: [] } });
  mocks.subjects.mockResolvedValue(success([{ id: 10, name: '待配置店铺', code: 'S10' }]));
});

describe('authorization center contract', () => {
  it('does not expose new authorization when the action is unavailable', async () => {
    const wrapper = create(); await flushPromises();
    expect(wrapper.findAll('button').some(button => button.text() === '新增授权')).toBe(false);
    expect(mocks.subjects).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('loads paginated subject candidates only after explicit authorized selection', async () => {
    mocks.permissions.push('integrations.view', 'integrations.store.authorize', 'masterdata.view');
    const wrapper = create(); await flushPromises();
    expect(mocks.subjects).not.toHaveBeenCalled(); await click(wrapper, '新增授权');
    expect(mocks.subjects).toHaveBeenCalledWith({ type: 'store', page: 1, page_size: 20, search: '' });
    expect(wrapper.text()).toContain('选择授权主体'); wrapper.unmount();
  });
  it('uses distinct query keys and expiry fields, omitting credentials', () => {
    expect(authorizationQuery('warehouse', 'jifeng_wms', 'active', 2)).toEqual({ provider: 'jifeng_wms', status: 'active', page: 2, page_size: 20 });
    expect(authorizationQuery('store', 'shopee', '', 1)).toEqual({ platform: 'shopee', page: 1, page_size: 20 });
    const result = authorizationSummary({ ...warehouse, token_expires_at: 'wrong', credential_mask: 'secret', email: 'private' }, 'warehouse');
    expect(result.expiresAt).toBe(warehouse.oauth_expires_at);
    expect(JSON.stringify(result)).not.toMatch(/wrong|secret|private/);
  });
  it('does not request either endpoint without existing read permission', async () => {
    mocks.permissions = []; const wrapper = create(); await flushPromises();
    expect(mocks.stores).not.toHaveBeenCalled(); expect(mocks.warehouses).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('当前账号没有授权查看权限'); wrapper.unmount();
  });
  it('uses only the warehouse endpoint for a warehouse-only user', async () => {
    mocks.permissions = ['integrations.warehouse.view']; const wrapper = create(); await flushPromises();
    expect(mocks.stores).not.toHaveBeenCalled(); expect(mocks.warehouses).toHaveBeenCalled();
    expect(wrapper.findComponent({ name: 'ElTable' }).props('data').map(row => row.name)).toEqual(['测试仓库']); wrapper.unmount();
  });
  it('drops stale store responses after switching domains', async () => {
    let finish; mocks.stores.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = create(); await flushPromises(); await click(wrapper, '仓库授权');
    finish(success([store])); await flushPromises();
    expect(wrapper.findComponent({ name: 'ElTable' }).props('data').map(row => row.name)).toEqual(['测试仓库']); wrapper.unmount();
  });
  it('reports list errors instead of keeping previously successful rows', async () => {
    const wrapper = create(); await flushPromises(); mocks.stores.mockResolvedValueOnce({ success: false, message: '权限已撤销' });
    await click(wrapper, '刷新'); expect(wrapper.text()).toContain('权限已撤销'); expect(wrapper.text()).not.toContain('测试店铺'); wrapper.unmount();
  });
});
