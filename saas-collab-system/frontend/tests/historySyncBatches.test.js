import { describe, expect, it, vi } from 'vitest';
import { shallowMount } from '@vue/test-utils';

const { fetchHistorySyncBatches, createHistorySyncBatch, actOnHistorySyncBatch, access, confirm } = vi.hoisted(() => ({
  access: { manage: true, live: true },
  fetchHistorySyncBatches: vi.fn().mockResolvedValue({ success: true, data: { batches: [], jobs: [
  { id: 1, shop_name: '可用店铺', resource_type: 'sales_order', is_enabled: true },
  { id: 5, shop_name: '可用店铺', resource_type: 'refund_return', is_enabled: true },
  { id: 6, shop_name: '可用店铺', resource_type: 'settlement_bill', is_enabled: true },
  { id: 2, shop_name: '已停用', resource_type: 'sales_order', is_enabled: false },
  { id: 3, shop_name: '阻塞店铺', resource_type: 'sales_order', is_enabled: true, blocked_reason: '缺少授权' },
  { id: 4, shop_name: '不支持类型', resource_type: 'platform_product', is_enabled: true },
  ] } }), createHistorySyncBatch: vi.fn(), actOnHistorySyncBatch: vi.fn(), confirm: vi.fn().mockResolvedValue(true),
}));
vi.mock('element-plus', async (importOriginal) => ({ ...(await importOriginal()), ElMessage: { success: vi.fn(), error: vi.fn() }, ElMessageBox: { confirm: (...args) => confirm(...args) } }));
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
  it('describes retry state accurately for paused and running batches', async () => {
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    expect(wrapper.vm.retryFailedStateHint({ status: 'paused' })).toContain('重试后仍保持暂停');
    expect(wrapper.vm.retryFailedStateHint({ status: 'paused' })).toContain('单独点击“继续”');
    expect(wrapper.vm.retryFailedStateHint({ status: 'running' })).toContain('如果批次已暂停');
    expect(wrapper.vm.retryFailedStateHint({ status: 'running' })).toContain('不会暂停批次');
    wrapper.unmount();
  });
  it.each(['manage','live'])('requires %s permission before allowing mutation controls', async (missing) => {
    access[missing] = false;
    fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { jobs: [], batches: [{ id: 3, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: false, blocked_reason: '有活动分段' } }] } });
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(wrapper.vm.canManage).toBe(false);
    expect(wrapper.text()).not.toContain('调整补采范围');
    wrapper.vm.openCreate();
    expect(wrapper.vm.dialog).toBe(false);
    wrapper.unmount();
    access[missing] = true;
  });
  it('captures revision, rejects unsafe ranges, and submits only explicit confirmed adjustment while paused', async () => {
    fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { jobs: [], batches: [] } });
    actOnHistorySyncBatch.mockResolvedValue({ success: true });
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    const batch = { id: 91, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, blocked_reason: '', protected_start_date: '2026-01-03', protected_end_date: '2026-01-08', revision: 'rev-7' } };
    wrapper.vm.openRangeAdjustment(batch);
    expect(wrapper.vm.rangeDialog).toBe(true);
    expect(wrapper.vm.rangeRevision).toBe('rev-7');
    expect(wrapper.vm.validRange).toBe(false); // unchanged dates
    wrapper.vm.rangeForm.start_date = '2026-01-04';
    wrapper.vm.rangeForm.end_date = '2026-01-09';
    expect(wrapper.vm.validRange).toBe(false); // excludes protected start
    wrapper.vm.rangeForm.start_date = '2025-12-30';
    wrapper.vm.rangeForm.end_date = '2026-01-09';
    expect(wrapper.vm.validRange).toBe(true);
    wrapper.vm.rangeForm.end_date = '2099-01-01';
    expect(wrapper.vm.validRange).toBe(false); // future
    expect(wrapper.vm.rangeValidationMessage).toContain('北京时间今天');
    wrapper.vm.rangeForm.start_date = '2026-02-30';
    wrapper.vm.rangeForm.end_date = '2026-03-01';
    expect(wrapper.vm.validRange).toBe(false); // invalid calendar date
    expect(wrapper.vm.rangeValidationMessage).toContain('有效的 YYYY-MM-DD');
    wrapper.vm.rangeForm.start_date = '2010-01-01';
    expect(wrapper.vm.validRange).toBe(false); // over 3660 days
    wrapper.vm.rangeForm.start_date = '2025-12-30';
    wrapper.vm.rangeForm.end_date = '2026-01-09';
    await wrapper.vm.submitRangeAdjustment();
    expect(confirm).toHaveBeenCalledOnce();
    expect(actOnHistorySyncBatch).toHaveBeenCalledWith(91, 'adjust_range', { start_date: '2025-12-30', end_date: '2026-01-09', expected_revision: 'rev-7' });
    wrapper.unmount();
  });
  it('does not open adjustment for running or server-blocked batches', async () => {
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    wrapper.vm.openRangeAdjustment({ id: 1, status: 'running', range_adjustment: { allowed: true, revision: 'r' } });
    expect(wrapper.vm.rangeDialog).toBe(false);
    wrapper.vm.openRangeAdjustment({ id: 2, status: 'paused', range_adjustment: { allowed: false, blocked_reason: '存在已提交分段' } });
    expect(wrapper.vm.rangeDialog).toBe(false);
    wrapper.unmount();
  });
  it('leaves the dialog open and makes no request when confirmation is cancelled', async () => {
    actOnHistorySyncBatch.mockClear();
    confirm.mockRejectedValueOnce(new Error('cancelled'));
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    wrapper.vm.openRangeAdjustment({ id: 92, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, revision: 'rev-8' } });
    wrapper.vm.rangeForm.start_date = '2025-12-31';
    await wrapper.vm.submitRangeAdjustment();
    expect(actOnHistorySyncBatch).not.toHaveBeenCalled();
    expect(wrapper.vm.rangeDialog).toBe(true);
    wrapper.unmount();
  });
  it('locks submission during confirmation and sends the captured id, dates, and revision only if permission remains', async () => {
    actOnHistorySyncBatch.mockClear();
    confirm.mockClear();
    let resolveConfirmation;
    confirm.mockReturnValueOnce(new Promise(resolve => { resolveConfirmation = resolve; }));
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    wrapper.vm.openRangeAdjustment({ id: 93, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, revision: 'rev-frozen' } });
    wrapper.vm.rangeForm.start_date = '2025-12-31';
    const first = wrapper.vm.submitRangeAdjustment();
    expect(wrapper.vm.busy).toBe('range_adjustment');
    await wrapper.vm.submitRangeAdjustment();
    expect(confirm).toHaveBeenCalledOnce();
    wrapper.vm.rangeRevision = 'rev-changed';
    wrapper.vm.rangeForm.start_date = '2025-12-30';
    resolveConfirmation(true);
    await first;
    expect(actOnHistorySyncBatch).toHaveBeenCalledWith(93, 'adjust_range', { start_date: '2025-12-31', end_date: '2026-01-10', expected_revision: 'rev-frozen' });
    expect(wrapper.vm.busy).toBe('');
    wrapper.unmount();
  });
  it('rechecks permissions after confirmation and refuses the request if permission was revoked', async () => {
    actOnHistorySyncBatch.mockClear();
    confirm.mockClear();
    let resolveConfirmation;
    confirm.mockReturnValueOnce(new Promise(resolve => { resolveConfirmation = resolve; }));
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    wrapper.vm.openRangeAdjustment({ id: 96, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, revision: 'rev-9' } });
    wrapper.vm.rangeForm.start_date = '2025-12-31';
    const pending = wrapper.vm.submitRangeAdjustment();
    access.manage = false;
    resolveConfirmation(true);
    await pending;
    expect(actOnHistorySyncBatch).not.toHaveBeenCalled();
    expect(wrapper.vm.rangeError).toContain('权限已变化');
    expect(wrapper.vm.busy).toBe('');
    access.manage = true;
    wrapper.unmount();
  });
  it('keeps the opened revision and edits after stale response while instructing close and reopen', async () => {
    actOnHistorySyncBatch.mockRejectedValueOnce(Object.assign(new Error('补采范围或分段状态已变化，请刷新批次后重新调整。'), { code: 'STALE_REVISION' }));
    fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { jobs: [], batches: [{ id: 94, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, revision: 'rev-new' } }] } });
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    wrapper.vm.openRangeAdjustment({ id: 94, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, revision: 'rev-old' } });
    wrapper.vm.rangeForm.start_date = '2025-12-31';
    await wrapper.vm.submitRangeAdjustment();
    expect(wrapper.vm.rangeRevision).toBe('rev-old');
    expect(wrapper.vm.rangeForm.start_date).toBe('2025-12-31');
    expect(wrapper.vm.rangeDialog).toBe(true);
    expect(wrapper.vm.rangeError).toContain('关闭此对话框并重新打开');
    wrapper.unmount();
  });
  it('accepts exactly 3660 days between valid dates and exposes a reason for an overlong range', async () => {
    const wrapper = shallowMount((await import('../src/components/HistorySyncBatches.vue')).default);
    wrapper.vm.openRangeAdjustment({ id: 95, status: 'paused', start_date: '2026-01-01', end_date: '2026-01-10', range_adjustment: { allowed: true, revision: 'rev' } });
    wrapper.vm.rangeForm.start_date = '2016-01-01';
    wrapper.vm.rangeForm.end_date = '2026-01-08';
    expect(wrapper.vm.validRange).toBe(true);
    wrapper.vm.rangeForm.start_date = '2015-12-31';
    expect(wrapper.vm.validRange).toBe(false);
    expect(wrapper.vm.rangeValidationMessage).toContain('3660 天');
    expect(wrapper.vm.rangeValidationMessage).toBe('开始和结束日期间隔不能超过 3660 天。');
    expect(wrapper.vm.rangeProtectedText).toBe('');
    wrapper.unmount();
  });
});
