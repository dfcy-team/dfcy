import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchLazadaOperations: vi.fn(), fetchLazadaReadHistory: vi.fn(), executeLazadaRead: vi.fn() }));
vi.mock('../src/api/integrations', () => api);
import Panel from '../src/components/LazadaReadonlyPanel.vue';

const accountOperation = { name: 'account_transactions', required: ['start_time', 'end_time', 'page_num', 'page_size'],
  optional: ['transaction_type', 'sub_transaction_type', 'transaction_number'], method: 'POST', path: '/finance/transaction/accountTransactions/query' };
async function accountPanel() {
  api.fetchLazadaOperations.mockResolvedValue({ success: true, data: { operations: [accountOperation] } });
  const wrapper = shallowMount(Panel, { props: { authorization: { id: 1 } }, global: { stubs: {
    ElCard: { template: '<section><slot name="header" /><slot /></section>' },
    ElForm: { template: '<form><slot /></form>' }, ElFormItem: { template: '<label><slot /></label>' },
  } } });
  await flushPromises(); return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchLazadaOperations.mockResolvedValue({ success: true, data: { operations: [{ name: 'seller', required: [], optional: [], path: '/seller/get', method: 'GET' }] } });
  api.fetchLazadaReadHistory.mockResolvedValue({ success: true, data: [] });
  api.executeLazadaRead.mockResolvedValue({ success: true, data: { id: 1, status: 'succeeded', response: { code: '0' } } });
});
describe('Lazada read-only panel', () => {
  it('provides account and ad-top-up shortcuts without automatically querying the platform', async () => {
    const wrapper = await accountPanel();
    wrapper.vm.selectAccount('Sponsored Solutions Top-up'); await flushPromises();
    expect(wrapper.vm.operationName).toBe('account_transactions');
    expect(wrapper.vm.accountForm.sub_transaction_type).toBe('Sponsored Solutions Top-up');
    expect(api.executeLazadaRead).not.toHaveBeenCalled();
    expect(wrapper.find('[aria-label="账户交易日期"]').exists()).toBe(true);
    wrapper.unmount();
  });
  it('sends official date, pagination and advertisement recharge parameters', async () => {
    const wrapper = await accountPanel(); wrapper.vm.selectAccount('Sponsored Solutions Top-up');
    wrapper.vm.accountForm.dates = ['20260901', '20260930'];
    wrapper.vm.accountForm.transaction_number = '  TX-001  ';
    await wrapper.vm.execute();
    expect(api.executeLazadaRead).toHaveBeenCalledWith(1, { operation: 'account_transactions', payload: {
      start_time: '20260901', end_time: '20260930', page_num: 1, page_size: 20,
      sub_transaction_type: 'Sponsored Solutions Top-up', transaction_number: 'TX-001',
    } });
    wrapper.unmount();
  });
  it('does not send incomplete or reversed account dates', async () => {
    const wrapper = await accountPanel(); wrapper.vm.selectAccount();
    for (const dates of [[], ['20261001', '20260930']]) {
      wrapper.vm.accountForm.dates = dates; await wrapper.vm.execute();
      expect(api.executeLazadaRead).not.toHaveBeenCalled(); expect(wrapper.vm.error).toContain('日期');
    }
    wrapper.unmount();
  });
  it('keeps the original money text and paginates the executed query, not unsaved filter changes', async () => {
    const wrapper = await accountPanel(); wrapper.vm.selectAccount();
    wrapper.vm.result = { operation: 'account_transactions', status: 'succeeded',
      parameters: { start_time: '20260901', end_time: '20260930', page_num: 1, page_size: 20 },
      response: { data: { page_info: { page_num: 1, page_size: 20, total_count: 21 },
        transactions: [{ transaction_number: 'TX-001', amount: '-999999999.123456', currency: 'PHP' }] } } };
    expect(wrapper.vm.accountPage.transactions[0].amount).toBe('-999999999.123456');
    expect(wrapper.vm.accountPage.page_info.total_page).toBe(2);
    expect(wrapper.vm.result.response.data.page_info.total_page).toBeUndefined();
    wrapper.vm.accountForm.dates = ['20261001', '20261030'];
    await wrapper.vm.loadAccountPage(2);
    expect(api.executeLazadaRead).toHaveBeenCalledWith(1, { operation: 'account_transactions', payload: {
      start_time: '20260901', end_time: '20260930', page_num: 2, page_size: 20,
    } });
    wrapper.unmount();
  });
  it('clears old successful data when a new account request fails', async () => {
    const wrapper = await accountPanel(); wrapper.vm.selectAccount();
    wrapper.vm.accountForm.dates = ['20260901', '20260930'];
    wrapper.vm.result = { id: 99, status: 'succeeded' };
    api.executeLazadaRead.mockRejectedValue(new Error('network failed'));
    await wrapper.vm.execute();
    expect(wrapper.vm.result).toBe(null); expect(wrapper.vm.error).toBeTruthy();
    wrapper.unmount();
  });
  it('does not call platform APIs on mount', async () => {
    const wrapper = shallowMount(Panel, { props: { authorization: { id: 1 } } });
    await flushPromises();
    expect(wrapper.vm.catalog).toHaveLength(1);
    expect(api.executeLazadaRead).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('unwraps the actual response envelope', async () => {
    const wrapper = shallowMount(Panel, { props: { authorization: { id: 1 } } });
    await flushPromises(); await wrapper.vm.execute();
    expect(api.executeLazadaRead).toHaveBeenCalledWith(1, { operation: 'seller', payload: {} });
    expect(wrapper.vm.result.id).toBe(1); wrapper.unmount();
  });
  it('does not convert an API rejection to success', async () => {
    api.executeLazadaRead.mockResolvedValue({ success: false, message: 'denied' });
    const wrapper = shallowMount(Panel, { props: { authorization: { id: 1 } } });
    await flushPromises(); await wrapper.vm.execute();
    expect(wrapper.vm.result).toBe(null);
    expect(wrapper.vm.error).toBeTruthy(); wrapper.unmount();
  });
  it('ignores a previous store query after switching stores', async () => {
    let resolve;
    api.executeLazadaRead.mockReturnValue(new Promise(done => { resolve = done; }));
    const wrapper = shallowMount(Panel, { props: { authorization: { id: 1 } } });
    await flushPromises(); const pending = wrapper.vm.execute();
    await wrapper.setProps({ authorization: { id: 2 } });
    resolve({ success: true, data: { id: 9 } }); await pending;
    expect(wrapper.vm.result).toBe(null); wrapper.unmount();
  });
});
