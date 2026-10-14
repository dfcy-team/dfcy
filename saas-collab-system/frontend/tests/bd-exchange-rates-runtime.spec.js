import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchConfigDefinitions: vi.fn(), fetchConfigValues: vi.fn(), createConfigValue: vi.fn(), approveConfigValue: vi.fn() }));
const auth = vi.hoisted(() => ({ currentUser: { id: 7 }, permissions: new Set(), hasPermission: vi.fn() }));
const messages = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock('../src/api/configCenter', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('element-plus', async importOriginal => ({ ...await importOriginal(), ElMessage: messages, ElMessageBox: { confirm } }));
import BdPerformanceExchangeRates from '../src/views/influencers/BdPerformanceExchangeRates.vue';

const KEY = 'influencers.bd.exchange_rates';
const rate = value => ({ currency: 'PHP', rate: value, effective_from: '2026-08-01', note: '' });
const version = (id, status, value) => ({ id, version: id, status, config_key: KEY, value: { rates: [rate(value)] }, effective_at: '2026-01-01T00:00:00Z' });
let active;
let latest;

beforeEach(() => {
  vi.clearAllMocks();
  active = version(1, 'effective', '0.12');
  latest = version(2, 'pending_approval', '0.13');
  auth.permissions = new Set(['config.view', 'config.manage']);
  auth.hasPermission.mockImplementation(code => auth.permissions.has(code));
  api.fetchConfigDefinitions.mockResolvedValue({ success: true, data: { items: [{ config_key: KEY, scope_type: 'tenant', requires_approval: false }] } });
  api.fetchConfigValues.mockImplementation(params => Promise.resolve({ success: true, data: { items: params.status === 'effective' ? [active] : [latest, active] } }));
  api.createConfigValue.mockResolvedValue({ success: true });
  confirm.mockResolvedValue('confirm');
});

describe('BD FX direct save', () => {
  it('retains a legacy pending draft without activating it and saves without approval', async () => {
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    expect(wrapper.vm.activeRows[0].rate).toBe('0.12');
    expect(wrapper.vm.rows[0].rate).toBe('0.13');
    expect(api.createConfigValue).not.toHaveBeenCalled();
    expect(wrapper.vm.canManage).toBe(true);
    await wrapper.vm.saveVersion();
    expect(api.createConfigValue).toHaveBeenCalledWith({ config_key: KEY, value: { rates: [rate('0.13')] }, effective_at: expect.any(String) });
    expect(api.approveConfigValue).not.toHaveBeenCalled();
    expect(messages.success).toHaveBeenCalledWith('汇率已保存并生效');
    wrapper.unmount();
  });
  it.each(['rate', 'effective_from', 'note'])('saves an edited %s in a new complete schedule', async field => {
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    const changed = { rate: '0.99', effective_from: '2026-09-01', note: 'changed' }[field];
    wrapper.vm.rows[0][field] = changed;
    expect(wrapper.vm.hasUnsavedChanges).toBe(true);
    expect(api.createConfigValue).not.toHaveBeenCalled();
    await wrapper.vm.saveVersion();
    expect(api.createConfigValue.mock.calls[0][0].value.rates[0][field]).toBe(changed);
    expect(api.approveConfigValue).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('confirms deletion and saves the last-row deletion as an empty schedule', async () => {
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    await wrapper.vm.removeRow(0);
    expect(confirm).toHaveBeenCalled();
    expect(wrapper.vm.rows).toEqual([]);
    expect(wrapper.vm.activeRows).toEqual([rate('0.12')]);
    expect(wrapper.vm.hasUnsavedChanges).toBe(true);
    expect(api.createConfigValue).not.toHaveBeenCalled();
    await wrapper.vm.saveVersion();
    expect(api.createConfigValue.mock.calls[0][0].value).toEqual({ rates: [] });
    expect(api.approveConfigValue).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('cancelled deletion preserves the draft and releases the confirmation lock', async () => {
    confirm.mockRejectedValueOnce('cancel');
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    await wrapper.vm.removeRow(0);
    expect(wrapper.vm.rows).toEqual([rate('0.13')]);
    expect(wrapper.vm.removing).toBe(false);
    expect(messages.error).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('blocks duplicate actions while deletion confirmation is pending', async () => {
    let resolve;
    confirm.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    const pending = wrapper.vm.removeRow(0);
    expect(wrapper.vm.canManage).toBe(false);
    await wrapper.vm.removeRow(0);
    await wrapper.vm.saveVersion();
    await wrapper.vm.load();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(api.createConfigValue).not.toHaveBeenCalled();
    resolve('confirm'); await pending;
    expect(wrapper.vm.rows).toEqual([]);
    wrapper.unmount();
  });
  it('enforces edit/delete permissions even when handlers are invoked directly', async () => {
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    auth.permissions = new Set(['config.view']);
    await wrapper.vm.saveVersion();
    await wrapper.vm.removeRow(0);
    wrapper.vm.addRow();
    expect(wrapper.vm.rows).toHaveLength(1);
    expect(api.createConfigValue).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('does not silently overwrite corrupt or incompatible saved fields', async () => {
    latest.value = { rates: [rate('0.13')], future_field: true };
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    expect(wrapper.vm.loadStatus).toBe('degraded');
    await wrapper.vm.saveVersion(); expect(api.createConfigValue).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('requires the deployed no-approval definition before allowing a save', async () => {
    api.fetchConfigDefinitions.mockResolvedValue({ success: true, data: { items: [{ config_key: KEY, scope_type: 'tenant', requires_approval: true }] } });
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    expect(wrapper.vm.canManage).toBe(false);
    await wrapper.vm.saveVersion(); expect(api.createConfigValue).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('keeps draft edits after a failed save and permits explicit retry', async () => {
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    wrapper.vm.rows[0].rate = '0.3';
    api.createConfigValue.mockRejectedValueOnce(new Error('network test'));
    await wrapper.vm.saveVersion();
    expect(wrapper.vm.saving).toBe(false);
    expect(wrapper.vm.rows[0].rate).toBe('0.3');
    expect(wrapper.vm.hasUnsavedChanges).toBe(true);
    await wrapper.vm.saveVersion(); expect(api.createConfigValue).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
  it('rejects invalid data before any POST', async () => {
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    wrapper.vm.rows[0].rate = '0';
    await wrapper.vm.saveVersion(); expect(api.createConfigValue).not.toHaveBeenCalled();
    expect(messages.error).toHaveBeenCalled();
    wrapper.unmount();
  });
  it('keeps edits disabled after a failed or mock read', async () => {
    api.fetchConfigValues.mockRejectedValueOnce(new Error('load test'));
    const wrapper = shallowMount(BdPerformanceExchangeRates); await flushPromises();
    expect(wrapper.vm.loadStatus).toBe('degraded');
    expect(wrapper.vm.loading).toBe(false);
    await wrapper.vm.load(); expect(wrapper.vm.loadStatus).toBe('connected');
    api.fetchConfigValues.mockResolvedValue({ success: true, data: { api_status: 'mock', items: [active] } });
    await wrapper.vm.load(); expect(wrapper.vm.loadStatus).toBe('degraded');
    wrapper.unmount();
  });
});
