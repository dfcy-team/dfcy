import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Panel from '../src/components/TikTokAdsSessionPanel.vue';
import { bindAds, discoverAds, getAdsSession, verifyAds } from '../src/api/tiktokAds';
vi.mock('../src/api/tiktokAds', () => ({ bindAds: vi.fn(), discoverAds: vi.fn(), getAdsSession: vi.fn(), verifyAds: vi.fn() }));
vi.mock('element-plus', async (original) => ({ ...await original(), ElMessage: { success: vi.fn() } }));
const state = { session_id: 'test-session', status: 'authorized', candidates: [
  { advertiser_id: '111', name: 'PHP account', currency: 'PHP', timezone: 'Asia/Manila', verify_state: 'verified' },
  { advertiser_id: '222', name: 'USD account', currency: 'USD', timezone: 'America/New_York', verify_state: 'failed' },
] };
const ok = (data = state) => ({ success: true, data });
const mountPanel = () => mount(Panel, { props: { sessionId: 'test-session' }, global: {
  directives: { loading: () => {} }, stubs: {
    ElButton: { template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>', props: ['disabled'], emits: ['click'] },
    ElAlert: { template: '<p>{{ title }}</p>', props: ['title'] },
    ElTable: { name: 'ElTable', template: '<div><slot /></div>', props: ['data'], emits: ['selection-change'] },
    ElTableColumn: { name: 'ElTableColumn', template: '<div />', props: ['selectable'] },
  },
} });
describe('Ads candidate workflow', () => {
  beforeEach(() => { vi.clearAllMocks(); getAdsSession.mockResolvedValue(ok()); });
  it('loads sanitized session and permits selection only for verified accounts', async () => {
    const wrapper = mountPanel(); await flushPromises();
    expect(getAdsSession).toHaveBeenCalledExactlyOnceWith('test-session');
    expect(wrapper.text()).toContain('不代表报表已入库');
    expect(wrapper.text()).toContain('系统自动核验后可确认绑定');
    expect(wrapper.text()).not.toContain('authorized');
    const selectable = wrapper.findAllComponents({ name: 'ElTableColumn' })[0].props('selectable');
    expect(selectable(state.candidates[0])).toBe(true);
    expect(selectable(state.candidates[1])).toBe(false);
    expect(wrapper.findAll('button').at(-1).attributes('disabled')).toBeDefined();
    wrapper.unmount();
  });
  it('binds only selected IDs with an idempotency key, without enabling sync', async () => {
    bindAds.mockResolvedValue(ok({ ...state, status: 'bound' }));
    const wrapper = mountPanel(); await flushPromises();
    wrapper.findComponent({ name: 'ElTable' }).vm.$emit('selection-change', [state.candidates[0]]);
    await flushPromises();
    await wrapper.findAll('button').at(-1).trigger('click'); await flushPromises();
    expect(bindAds).toHaveBeenCalledWith('test-session', { advertiser_ids: ['111'], idempotency_key: expect.any(String) });
    expect(wrapper.emitted('bound')).toHaveLength(1);
    expect(verifyAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('allows safe discovery retry and explains preserved authorization on failure', async () => {
    discoverAds.mockResolvedValue(ok({ ...state, discovery_failed: true }));
    const wrapper = mountPanel(); await flushPromises();
    await wrapper.findAll('button')[1].trigger('click'); await flushPromises();
    expect(discoverAds).toHaveBeenCalledExactlyOnceWith('test-session');
    expect(wrapper.text()).toContain('授权已保存');
    expect(bindAds).not.toHaveBeenCalled();
    expect(verifyAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('automatically verifies every newly discovered account without binding or syncing', async () => {
    const pending = structuredClone(state);
    pending.candidates.forEach(row => { row.verify_state = 'unverified'; });
    getAdsSession.mockResolvedValue(ok(pending));
    verifyAds.mockImplementation(async (_sessionId, identifier) => {
      const row = pending.candidates.find(candidate => candidate.advertiser_id === identifier);
      row.verify_state = 'verified';
      return ok(structuredClone(pending));
    });
    const wrapper = mountPanel(); await flushPromises();
    expect(verifyAds.mock.calls).toEqual([['test-session', '111'], ['test-session', '222']]);
    const selectable = wrapper.findAllComponents({ name: 'ElTableColumn' })[0].props('selectable');
    expect(selectable(pending.candidates[0])).toBe(true);
    expect(selectable(pending.candidates[1])).toBe(true);
    expect(bindAds).not.toHaveBeenCalled();
    await wrapper.findAll('button')[0].trigger('click'); await flushPromises();
    expect(verifyAds).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
  it('keeps failed accounts unselectable, continues other accounts and does not loop retries', async () => {
    const snapshot = structuredClone(state);
    snapshot.candidates.forEach(row => { row.verify_state = 'unverified'; });
    getAdsSession.mockResolvedValue(ok(snapshot));
    verifyAds.mockImplementation(async (_sessionId, identifier) => {
      snapshot.candidates.find(candidate => candidate.advertiser_id === identifier).verify_state = identifier === '111' ? 'failed' : 'verified';
      return ok(structuredClone(snapshot));
    });
    const wrapper = mountPanel(); await flushPromises();
    const selectable = wrapper.findAllComponents({ name: 'ElTableColumn' })[0].props('selectable');
    expect(selectable(snapshot.candidates[0])).toBe(false);
    expect(selectable(snapshot.candidates[1])).toBe(true);
    expect(wrapper.text()).toContain('部分账户未通过自动验证');
    expect(verifyAds).toHaveBeenCalledTimes(2);
    expect(bindAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('stops automatic verification on a denied request without fabricating success', async () => {
    const pending = structuredClone(state);
    pending.candidates.forEach(row => { row.verify_state = 'unverified'; });
    getAdsSession.mockResolvedValue(ok(pending));
    verifyAds.mockResolvedValue({ success: false, http_status: 403 });
    const wrapper = mountPanel(); await flushPromises();
    expect(verifyAds).toHaveBeenCalledExactlyOnceWith('test-session', '111');
    expect(wrapper.text()).toContain('核对权限或配置');
    expect(bindAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('does not automatically retry failed accounts or access a bound session', async () => {
    getAdsSession.mockResolvedValue(ok({ ...state, status: 'bound' }));
    const wrapper = mountPanel(); await flushPromises();
    expect(verifyAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('does not make verification calls when the session read is denied', async () => {
    getAdsSession.mockResolvedValue({ success: false, http_status: 403 });
    const wrapper = mountPanel(); await flushPromises();
    expect(verifyAds).not.toHaveBeenCalled();
    expect(bindAds).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('核对权限或配置');
    wrapper.unmount();
  });
  it('stops after a network interruption without retrying or verifying the next account', async () => {
    const pending = structuredClone(state);
    pending.candidates.forEach(row => { row.verify_state = 'unverified'; });
    getAdsSession.mockResolvedValue(ok(pending));
    verifyAds.mockRejectedValue(new Error('synthetic network interruption'));
    const wrapper = mountPanel(); await flushPromises();
    expect(verifyAds).toHaveBeenCalledExactlyOnceWith('test-session', '111');
    expect(wrapper.text()).toContain('自动验证可能尚未完成');
    expect(bindAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('discards a late response after moving to another authorization session', async () => {
    let resolveFirst;
    const pending = structuredClone(state);
    pending.candidates[0].verify_state = 'unverified';
    getAdsSession.mockResolvedValueOnce(ok(pending));
    verifyAds.mockReturnValue(new Promise(resolve => { resolveFirst = resolve; }));
    const wrapper = mountPanel(); await flushPromises();
    expect(wrapper.text()).toContain('正在自动核验');
    getAdsSession.mockResolvedValueOnce(ok({ session_id: 'second-session', status: 'bound', candidates: [] }));
    await wrapper.setProps({ sessionId: 'second-session' }); await flushPromises();
    resolveFirst(ok({ ...state, status: 'authorized' })); await flushPromises();
    expect(wrapper.text()).toContain('已绑定，同步未启用');
    expect(wrapper.text()).not.toContain('正在自动核验');
    expect(verifyAds).toHaveBeenCalledTimes(1);
    expect(bindAds).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
