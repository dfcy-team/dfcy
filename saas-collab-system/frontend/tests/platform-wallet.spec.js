import { mount, flushPromises } from '@vue/test-utils';
import { computed } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchPlatformWallet: vi.fn(), fetchApiWithdrawals: vi.fn(), syncPlatformWallet: vi.fn(), saveWalletSchedule: vi.fn() }));
vi.mock('../src/api/financeReconciliation', () => api);
import Page from '../src/views/finance/WithdrawalRecordList.vue';

const store = { store_id: 1, store_name: 'Synthetic Shop', store_code: 'SYNTHETIC', platform: 'lazada', balance: null,
  balance_note: '余额接口尚未核验', withdrawal_capability: { withdrawals: true, note: '提款流水' } };
const stubs = {
  'el-button': { props: ['disabled', 'loading', 'nativeType'], template: '<button :disabled="disabled || loading" :type="nativeType || \'button\'"><slot /></button>' },
  'el-alert': { props: ['title'], template: '<p role="alert">{{ title }}</p>' },
  'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<label><slot /></label>' },
  'el-select': true, 'el-option': true, 'el-switch': true, 'el-input-number': true, 'el-input': true, 'el-pagination': true,
  'el-table': { props: ['data', 'emptyText'], provide() { return { rows: computed(() => this.data) }; }, template: '<div><p v-if="!data.length">{{ emptyText }}</p><slot /></div>' },
  'el-table-column': { props: ['label', 'prop'], inject: ['rows'], template: '<section>{{ label }}<div v-for="row in rows"><slot :row="row">{{ row[prop] }}</slot></div></section>' }
};
let wrapper;
const render = () => (wrapper = mount(Page, { global: { stubs, directives: { loading: () => {} } } }));
function overview(state = 'idle', canSync = true) {
  return { success: true, data: { stores: [store], can_sync: canSync, sync: { enabled: false, interval_minutes: 60, state, activated_at: null } } };
}
beforeEach(() => {
  vi.clearAllMocks();
  api.fetchPlatformWallet.mockResolvedValue(overview());
  api.fetchApiWithdrawals.mockResolvedValue({ success: true, data: { items: [], pagination: { total: 0 } } });
});
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); });

describe('平台余额与API提款记录', () => {
  it('reads locally on mount and does not initiate synchronization or create a schedule', async () => {
    render(); await flushPromises();
    expect(wrapper.text()).toContain('未获取');
    expect(wrapper.text()).not.toContain('0 PHP');
    expect(api.syncPlatformWallet).not.toHaveBeenCalled();
    expect(api.saveWalletSchedule).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('不显示旧导入或手工登记数据');
  });
  it('preserves original signed text, reversal and missing status without inventing receipt', async () => {
    api.fetchApiWithdrawals.mockResolvedValue({ success: true, data: { items: [{ id: 1, platform: 'lazada',
      store_name: 'Synthetic Shop', store_code: 'SYNTHETIC', withdrawal_no: 'SYNTHETIC-1', amount: '-1,234.560000',
      currency: 'PHP', transaction_type: 'REVERSE', status: null, source_endpoint: '/synthetic/read', occurred_at_utc: null }], pagination: { total: 1 } } });
    render(); await flushPromises();
    expect(wrapper.text()).toContain('-1,234.560000 PHP');
    expect(wrapper.text()).toContain('提款退回');
    expect(wrapper.text()).toContain('接口未返回');
    expect(wrapper.findAll('section').some(node => node.text() === '已到账')).toBe(false);
  });
  it('submits a manual job only after clicking and keeps queued distinct from succeeded', async () => {
    vi.useFakeTimers();
    api.syncPlatformWallet.mockResolvedValue({ success: true, data: { dispatched: false, message: '等待队列恢复' } });
    render(); await flushPromises();
    api.fetchPlatformWallet.mockResolvedValue(overview('queued'));
    await wrapper.findAll('button').find(button => button.text() === '手动同步').trigger('click'); await flushPromises();
    expect(api.syncPlatformWallet).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('等待队列恢复');
    expect(wrapper.text()).toContain('排队中');
    expect(wrapper.findAll('button').find(button => button.text() === '手动同步').attributes('disabled')).toBeDefined();
    expect(wrapper.text()).not.toContain('已完成本次同步');
  });
  it('hides mutation controls for viewers', async () => {
    api.fetchPlatformWallet.mockResolvedValue(overview('idle', false));
    render(); await flushPromises();
    expect(wrapper.findAll('button').some(button => button.text() === '手动同步')).toBe(false);
    expect(wrapper.findAll('button').some(button => button.text() === '保存同步设置')).toBe(false);
  });
  it('filters records on the server and never syncs during search', async () => {
    render(); await flushPromises();
    Object.assign(wrapper.vm.filters, { platform: 'lazada', store_id: 1, currency: 'php', status: 'PROCESSING' });
    wrapper.vm.page = 4;
    wrapper.vm.search(); await flushPromises();
    expect(api.fetchApiWithdrawals).toHaveBeenLastCalledWith({ platform: 'lazada', store_id: 1, currency: 'PHP', status: 'PROCESSING', page: 1, page_size: 20 });
    expect(api.syncPlatformWallet).not.toHaveBeenCalled();
  });
  it('makes failed reads visible rather than reporting empty success', async () => {
    api.fetchApiWithdrawals.mockRejectedValue(new Error('SYNTHETIC-PRIVATE-ERROR'));
    render(); await flushPromises();
    expect(wrapper.text()).toContain('读取失败');
    expect(wrapper.text()).not.toContain('SYNTHETIC-PRIVATE');
  });
  it('saves an opt-in interval without starting an immediate backfill', async () => {
    render(); await flushPromises();
    Object.assign(wrapper.vm.schedule, { enabled: true, interval_minutes: 120 });
    api.saveWalletSchedule.mockResolvedValue({ success: true, data: { enabled: true, interval_minutes: 120, state: 'idle' } });
    await wrapper.findAll('form')[0].trigger('submit'); await flushPromises();
    expect(api.saveWalletSchedule).toHaveBeenCalledWith({ enabled: true, interval_minutes: 120 });
    expect(api.syncPlatformWallet).not.toHaveBeenCalled();
  });
});
