import { describe, expect, it, vi } from 'vitest';
import { shallowMount } from '@vue/test-utils';

const { fetchHistorySyncBatches, createHistorySyncBatch, actOnHistorySyncBatch, access } = vi.hoisted(() => ({
  access: { manage: true, live: true },
  fetchHistorySyncBatches: vi.fn().mockResolvedValue({ success: true, data: { batches: [], jobs: [
  { id: 1, shop_name: '可用店铺', resource_type: 'sales_order', is_enabled: true },
  { id: 5, shop_name: '可用店铺', resource_type: 'refund_return', is_enabled: true },
  { id: 6, shop_name: '可用店铺', resource_type: 'settlement_bill', is_enabled: true },
  { id: 2, shop_name: '已停用', resource_type: 'sales_order', is_enabled: false },
  { id: 3, shop_name: '阻塞店铺', resource_type: 'sales_order', is_enabled: true, blocked_reason: '缺少授权' },
  { id: 4, shop_name: '不支持类型', resource_type: 'platform_product', is_enabled: true },
  ] } }), createHistorySyncBatch: vi.fn(), actOnHistorySyncBatch: vi.fn(),
}));
vi.mock('../src/api/integrations', () => ({
  fetchHistorySyncBatches: (...args) => fetchHistorySyncBatches(...args),
  createHistorySyncBatch: (...args) => createHistorySyncBatch(...args),
  actOnHistorySyncBatch: (...args) => actOnHistorySyncBatch(...args),
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: permission => permission === 'integrations.history.view' || (permission === 'integrations.history.manage' && access.manage) || (permission === 'integrations.run_live_readonly' && access.live) }) }));

describe('Shopee history sync batch UI', () => {
  it('loads batches and offers all three enabled, unblocked Shopee history resources', async () => {
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default, {
      global: { stubs: { ElButton: true, ElAlert: true, ElEmpty: true, ElProgress: true, ElDialog: true, ElForm: true, ElFormItem: true, ElInput: true, ElSelect: true, ElOption: true, ElDatePicker: true } },
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(fetchHistorySyncBatches).toHaveBeenCalledOnce();
    expect(wrapper.vm.eligibleJobs.map(job => job.id)).toEqual([1, 5, 6]);
    expect(wrapper.vm.resourceLabel('sales_order')).toBe('销售订单');
    expect(wrapper.vm.resourceLabel('refund_return')).toBe('退货退款');
    expect(wrapper.vm.resourceLabel('settlement_bill')).toBe('财务流水');
    expect(wrapper.find('el-alert-stub').attributes('title')).toContain('平台可能不会保留所选日期的全部数据');
    wrapper.unmount();
  });
  it.each(['manage','live'])('requires %s permission before allowing mutation controls', async (missing) => {
    access[missing] = false;
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    expect(wrapper.vm.canManage).toBe(false);
    wrapper.vm.openCreate();
    expect(wrapper.vm.dialog).toBe(false);
    wrapper.unmount();
    access[missing] = true;
  });
});
