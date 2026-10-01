// @vitest-environment jsdom
import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ElementPlus from 'element-plus';
import SsoAuthorize from '../src/views/auth/SsoAuthorize.vue';

const state = vi.hoisted(() => ({ route: { query: {} }, request: vi.fn() }));
vi.mock('vue-router', () => ({ useRoute: () => state.route }));
vi.mock('../src/api/request', () => ({ requestApi: (...args) => state.request(...args) }));
const query = { client_id: 'caller', redirect_uri: 'https://caller.example/callback', state: 'random_state_12345678', code_challenge: 'a'.repeat(43) };
const render = () => mount(SsoAuthorize, { global: { plugins: [ElementPlus] } });

describe('employee delegation consent remains separate from identity SSO', () => {
  beforeEach(() => {
    state.route.query = { ...query };
    state.request.mockReset().mockResolvedValue({ success: false, message: '员工委托尚未启用' });
  });
  it('keeps default identity mode on the original endpoint', async () => {
    const wrapper = render();
    expect(wrapper.text()).toContain('确认共用登录');
    await wrapper.get('button').trigger('click');
    expect(state.request).toHaveBeenCalledWith({ method: 'post', url: '/api/internal/integrations/sso/authorize/', data: query, noMockFallback: true });
    wrapper.unmount();
  });
  it('requires explicit purpose and audience and displays scoped readonly consent', async () => {
    state.route.query = { ...query, purpose: 'employee_readonly', audience: 'employee-readonly-v1' };
    const wrapper = render();
    expect(wrapper.text()).toContain('确认员工只读委托');
    expect(wrapper.text()).toContain('原生权限');
    await wrapper.get('button').trigger('click');
    await vi.waitFor(() => expect(wrapper.text()).toContain('员工委托尚未启用'));
    expect(state.request).toHaveBeenCalledWith({ method: 'post', url: '/api/employee-readonly/v1/authorize/', data: { ...query, audience: 'employee-readonly-v1' }, noMockFallback: true });
    wrapper.unmount();
  });
  it.each([
    { purpose: 'employee_readonly', audience: 'wrong' },
    { purpose: 'unknown' },
    { purpose: 'employee_readonly' },
    { audience: 'employee-readonly-v1' },
  ])('rejects invalid mode without downgrading to SSO: %j', async (extra) => {
    state.route.query = { ...query, ...extra };
    const wrapper = render();
    expect(wrapper.get('button').element.disabled).toBe(true);
    await wrapper.get('button').trigger('click');
    expect(state.request).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
