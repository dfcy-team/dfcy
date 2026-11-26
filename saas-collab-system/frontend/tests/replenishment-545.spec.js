import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
const api = vi.hoisted(() => ({ rows: vi.fn(), strategy: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentJobRows: api.rows, fetchReplenishmentStrategy: api.strategy, fetchDailyReplenishment: vi.fn() }));
import OperatingReferenceV2 from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const mountView = () => {
  setActivePinia(createPinia());
  useAuthStore().setCurrentUser({ user_type: 'internal', permissions: ['supply.v2.view'], action_permission_codes: ['supply.v2.view'] });
  return mount(OperatingReferenceV2, { props: { parameters: { country_id: 3, source_kind: 'cycle' }, floatingBasket: true }, global: { stubs: { 'el-alert': true, 'el-table': true, 'el-table-column': true, 'el-select': true, 'el-option': true, 'el-button': true, 'el-checkbox': true, 'el-pagination': true, 'el-input-number': true, 'el-drawer': true, 'el-tag': true, 'el-progress': true, 'el-input': true, 'el-popover': true, 'el-checkbox-group': true, 'el-cascader': true, 'el-dialog': true, 'el-empty': true, 'el-descriptions': true, 'el-descriptions-item': true, OperatingProductImageV2: true, DocumentSkuV2: true, InventoryAbcBadges: true }, directives: { loading: () => {} } } });
};
describe('V545 replenishment UI', () => {
  beforeEach(() => { api.strategy.mockReset().mockResolvedValue({ success: true, data: { configured: false } }); api.rows.mockReset(); });
  it('retries transient SKU detail failure once and permits another attempt after failure', async () => {
    api.rows.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce({ success: true, data: { rows: [{ sku_id: 2, suggested_quantity: 4, stock_balance_quantity: -3 }], count: 1 } });
    const wrapper = mountView(); wrapper.vm.jobId = 'job-test'; const group = { spu_id: 9 };
    await wrapper.vm.loadSkuDetails(group); await flushPromises();
    expect(api.rows).toHaveBeenCalledTimes(2);
    expect(wrapper.vm.skuDetails[9].error).toContain('网络暂时不稳定');
    await wrapper.vm.loadSkuDetails(group); await flushPromises();
    expect(api.rows).toHaveBeenCalledTimes(3); expect(wrapper.vm.skuDetails[9].rows[0].stock_balance_quantity).toBe(-3);
    wrapper.unmount();
  });
  it('does not retry authorization failures and shows signed inventory balance', async () => {
    api.rows.mockResolvedValue({ success: false, http_status: 403, message: 'forbidden' });
    const wrapper = mountView(); wrapper.vm.jobId = 'job-test'; await wrapper.vm.loadSkuDetails({ spu_id: 4 }); await flushPromises();
    expect(api.rows).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.skuDetails[4].error).toContain('无权读取');
    wrapper.unmount();
  });
});
