import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const mocks = vi.hoisted(() => ({ status: vi.fn(), start: vi.fn(), complete: vi.fn(), mountQr: vi.fn(), useMock: false }));
vi.mock('../src/api/auth', () => ({
  getFeishuBindingStatus: mocks.status,
  startFeishuBinding: mocks.start,
  completeFeishuBinding: mocks.complete,
  getMyProfile: vi.fn(),
  updateMyProfile: vi.fn(),
  changeMyPassword: vi.fn(),
}));
vi.mock('../src/api/request', () => ({ useMock: mocks.useMock }));
vi.mock('../src/utils/feishuQrLogin', () => ({ mountFeishuQr: mocks.mountQr }));

import FeishuBindingPanel from '../src/components/FeishuBindingPanel.vue';
import UserSettingsDrawer from '../src/components/UserSettingsDrawer.vue';

const stubs = {
  'el-skeleton': { template: '<div>loading</div>' },
  'el-alert': { props: ['title', 'type'], template: '<div role="alert" :data-alert-type="type">{{ title }}</div>' },
  'el-form': { emits: ['submit'], template: '<form @submit="$emit(\'submit\', $event)"><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-input': {
    props: ['modelValue', 'type', 'autocomplete'],
    emits: ['update:modelValue', 'keyup'],
    template: '<input :type="type" :value="modelValue" :autocomplete="autocomplete" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-button': { props: ['nativeType', 'disabled'], template: '<button :type="nativeType || \'button\'" :disabled="disabled"><slot /></button>' },
};

describe('个人飞书绑定', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useMock = false;
    mocks.status.mockResolvedValue({ success: true, data: { enabled: true, bound: false, status: null, bound_at: null, username: 'alice' } });
    mocks.start.mockResolvedValue({ success: true, data: { authorize_url: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=x&redirect_uri=https%3A%2F%2Fapp.test%2F&response_type=code&state=s', expires_in: 300 } });
    mocks.complete.mockResolvedValue({ success: true, data: { enabled: true, bound: true, status: 'active', bound_at: '2026-10-14T00:00:00Z', username: 'alice' } });
    mocks.mountQr.mockResolvedValue(vi.fn());
    vi.stubGlobal('requestAnimationFrame', (callback) => { callback(); return 1; });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('opens the binding tab immediately when a fresh layout returns from OAuth', async () => {
    const wrapper = mount(UserSettingsDrawer, {
      props: { modelValue: true, initialTab: 'binding', callbackMarker: 'fresh-oauth-return' },
      global: { stubs: { ...stubs,
        'el-drawer': { props: ['modelValue'], template: '<section v-if="modelValue"><slot /></section>' },
        'el-tabs': { props: ['modelValue'], template: '<div :data-active-tab="modelValue"><slot /></div>' },
        'el-tab-pane': { template: '<section><slot /></section>' },
        'el-input-number': true,
      } },
    });
    await flushPromises();
    expect(wrapper.find('[data-active-tab]').attributes('data-active-tab')).toBe('binding');
    expect(mocks.complete).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain('已绑定飞书账号');
    wrapper.unmount();
  });

  it('verifies the entered password, clears it, and mounts the official QR helper', async () => {
    const wrapper = mount(FeishuBindingPanel, { props: { active: true }, global: { stubs } });
    await flushPromises();
    await wrapper.find('input').setValue('correct horse battery staple');
    await wrapper.find('form').trigger('submit');
    await flushPromises();
    expect(mocks.start).toHaveBeenCalledWith('correct horse battery staple');
    expect(mocks.mountQr).toHaveBeenCalledWith(expect.objectContaining({ id: 'feishu-binding-qr', authorizeUrl: expect.stringContaining('state=s') }));
    expect(wrapper.find('input').element.value).toBe('');
    expect(wrapper.text()).toContain('请使用您要绑定的飞书账号扫描二维码');
    wrapper.unmount();
  });

  it('completes a callback once and renders the current-user bound state', async () => {
    const wrapper = mount(FeishuBindingPanel, { props: { active: true, callbackMarker: 'callback-1' }, global: { stubs } });
    await flushPromises();
    expect(mocks.complete).toHaveBeenCalledTimes(1);
    expect(mocks.mountQr).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('已绑定飞书账号');
    expect(wrapper.text()).toContain('如需更换绑定的飞书账号，请联系管理员处理');
    expect(wrapper.emitted('callback-consumed')).toEqual([['callback-1']]);
    wrapper.unmount();
  });

  it('shows an inactive existing binding as unavailable for Feishu QR login', async () => {
    mocks.status.mockResolvedValue({ success: true, data: { enabled: true, bound: true, status: 'inactive', bound_at: null, username: 'alice' } });
    const wrapper = mount(FeishuBindingPanel, { props: { active: true }, global: { stubs } });
    await flushPromises();
    const alert = wrapper.get('[role="alert"]');
    expect(alert.attributes('data-alert-type')).toBe('warning');
    expect(alert.text()).toContain('当前已停用，不能用于飞书扫码登录');
    expect(wrapper.find('form').exists()).toBe(false);
    wrapper.unmount();
  });

  it('shows identity conflicts without automatically starting another QR', async () => {
    mocks.start.mockResolvedValue({ success: false, code: 'identity_in_use' });
    const wrapper = mount(FeishuBindingPanel, { props: { active: true }, global: { stubs } });
    await flushPromises();
    await wrapper.find('input').setValue('correct horse battery staple');
    await wrapper.find('form').trigger('submit');
    await flushPromises();
    expect(wrapper.text()).toContain('该飞书账号已绑定其他系统账号');
    expect(mocks.mountQr).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('ignores a start response after the binding tab is hidden', async () => {
    let resolveStart;
    mocks.start.mockReturnValue(new Promise((resolve) => { resolveStart = resolve; }));
    const wrapper = mount(FeishuBindingPanel, { props: { active: true }, global: { stubs } });
    await flushPromises();
    await wrapper.find('input').setValue('secret');
    await wrapper.find('form').trigger('submit');
    await wrapper.setProps({ active: false });
    resolveStart({ success: true, data: { authorize_url: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=x&redirect_uri=https%3A%2F%2Fapp.test%2F&response_type=code&state=s', expires_in: 300 } });
    await flushPromises();
    expect(mocks.mountQr).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('resets busy state on hide and keeps a new password when an old start request returns', async () => {
    let resolveOldStart;
    mocks.start.mockReturnValueOnce(new Promise((resolve) => { resolveOldStart = resolve; }));
    const wrapper = mount(FeishuBindingPanel, { props: { active: true }, global: { stubs } });
    await flushPromises();
    await wrapper.find('input').setValue('old password');
    await wrapper.find('form').trigger('submit');
    await wrapper.setProps({ active: false });
    await wrapper.setProps({ active: true });
    await flushPromises();
    await wrapper.find('input').setValue('new password');
    resolveOldStart({ success: true, data: { authorize_url: 'https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=x&redirect_uri=https%3A%2F%2Fapp.test%2F&response_type=code&state=s', expires_in: 300 } });
    await flushPromises();
    expect(wrapper.find('input').element.value).toBe('new password');
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined();
    wrapper.unmount();
  });

  it('does not start QR when binding status cannot be confirmed', async () => {
    mocks.status.mockResolvedValue({ success: false, code: 'provider_error' });
    const wrapper = mount(FeishuBindingPanel, { props: { active: true }, global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('无法确认飞书绑定状态');
    expect(wrapper.find('form').exists()).toBe(false);
    expect(mocks.start).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('refreshes status after already_bound callback failure while preserving the error', async () => {
    mocks.status
      .mockResolvedValueOnce({ success: true, data: { enabled: true, bound: false, status: null, bound_at: null, username: 'alice' } })
      .mockResolvedValueOnce({ success: true, data: { enabled: true, bound: true, status: 'active', bound_at: null, username: 'alice' } });
    mocks.complete.mockResolvedValue({ success: false, code: 'already_bound' });
    const wrapper = mount(FeishuBindingPanel, { props: { active: true, callbackMarker: 'callback-existing' }, global: { stubs } });
    await flushPromises();
    expect(mocks.status).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain('已绑定飞书账号');
    expect(wrapper.text()).toContain('此账号已绑定飞书，如需更换请联系管理员。');
    wrapper.unmount();
  });
});
