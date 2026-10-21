import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({
  fetchInventoryAlerts: vi.fn(), fetchInventoryAlert: vi.fn(), fetchInventoryAlertAssignees: vi.fn(),
  updateInventoryAlertFollowUp: vi.fn(), closeInventoryAlert: vi.fn()
}));
vi.mock('../src/api/alerts', () => api);
vi.mock('../src/api/request', () => ({ useMock: false }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), currentRoute: { value: { query: {} } } }) }));
import { useAuthStore } from '../src/stores/auth';

const alertRow = {
  id: 31, sku_code: 'SKU-31', product_name: '商品 A', warehouse_code: 'WH-1', alert_type: 'stockout_risk', severity: 'high',
  coverage_days: '2.0000', status: 'open', assigned_to_id: null, assigned_to_name: '', action_plan: '原处理方案', due_date: null,
  resolution: '', version: 4, events: [], reason: '覆盖不足', source_summary: { mode: 'real_observation', evaluation_status: 'pending', evaluated_at: '2026-10-20T10:00:00Z', data_at: '2026-10-20T09:00:00Z', blocked_issues: ['missing_inventory_snapshot'] }
};
const ok = data => ({ success: true, code: 'OK', message: 'success', data });
const collection = row => ok({ count: row ? 1 : 0, results: row ? [row] : [] });
let wrapper, auth;

beforeEach(() => {
  vi.clearAllMocks(); setActivePinia(createPinia());
  auth = useAuthStore();
  auth.setCurrentUser({ id: 9, user_type: 'internal', permissions: ['alerts.manage'] });
  api.fetchInventoryAlerts.mockResolvedValue(collection(alertRow));
  api.fetchInventoryAlertAssignees.mockResolvedValue(ok([{ id: 8, name: '采购同事' }]));
  api.fetchInventoryAlert.mockResolvedValue(ok(alertRow));
  api.updateInventoryAlertFollowUp.mockResolvedValue(ok({ ...alertRow, version: 5 }));
  api.closeInventoryAlert.mockResolvedValue(ok({ ...alertRow, status: 'closed', version: 5, resolution: '完成' }));
});

async function mountPage() {
  const { default: Page } = await import('../src/views/inventory/InventoryAlertList.vue');
  wrapper = mount(Page, { attachTo: document.body, global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

describe('inventory alert follow-up page', () => {
  it('loads real inventory fields and keeps edited values when save fails', async () => {
    await mountPage();
    expect(wrapper.text()).toContain('SKU-31');
    expect(wrapper.text()).toContain('商品 A');
    expect(wrapper.text()).toContain('2.0000');
    await wrapper.get('button').trigger('click');
    await flushPromises();
    const followUp = wrapper.findAll('button').find(button => button.text().includes('跟进'));
    await followUp.trigger('click');
    await flushPromises();
    const textarea = wrapper.find('textarea');
    await textarea.setValue('保留的方案草稿');
    api.updateInventoryAlertFollowUp.mockResolvedValueOnce({ success: false, message: '版本冲突', data: null });
    await wrapper.findAll('button').find(button => button.text().includes('保存跟进')).trigger('click');
    await flushPromises();
    expect(wrapper.find('textarea').element.value).toBe('保留的方案草稿');
    expect(wrapper.text()).toContain('版本冲突');
    expect(api.updateInventoryAlertFollowUp).toHaveBeenCalledWith(31, expect.objectContaining({ expected_version: 4 }));
  });

  it('does not render an old list response after authorization becomes stale', async () => {
    let resolveList;
    api.fetchInventoryAlerts.mockReturnValueOnce(new Promise(resolve => { resolveList = resolve; }));
    await mountPage();
    auth.authorizationStale = true;
    resolveList(collection(alertRow));
    await flushPromises();
    expect(wrapper.text()).not.toContain('SKU-31');
    expect(api.fetchInventoryAlertAssignees).not.toHaveBeenCalled();
  });

  it('queries only effective real observations by default and exposes review evidence tabs', async () => {
    await mountPage();
    expect(api.fetchInventoryAlerts).toHaveBeenCalledWith(expect.objectContaining({ validity: 'valid', source_mode: 'real_observation' }));
    expect(wrapper.text()).toContain('待核对');
    expect(wrapper.text()).toContain('缺少库存快照');
    expect(wrapper.text()).toContain('评估状态');
    expect(wrapper.text()).toContain('待核对数据');
    wrapper.vm.validity = 'all'; await wrapper.vm.loadAlerts(); await flushPromises();
    expect(api.fetchInventoryAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ validity: 'all', source_mode: 'real_observation' }));
  });
});
