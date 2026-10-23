import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ requestApi: vi.fn() }));
vi.mock('../src/api/request', () => api);

import LocalDemoUpdate from '../src/components/LocalDemoUpdate.vue';

const ok = data => ({ success: true, data });
const state = (status = 'idle', previous_available = false) => ({
  enabled: true,
  status,
  error_code: '',
  previous_available
});
const stubs = {
  ElButton: {
    props: ['disabled', 'loading'],
    emits: ['click'],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>'
  },
  ElTooltip: { template: '<span><slot /></span>' }
};
const mountWidget = () => mount(LocalDemoUpdate, { global: { stubs } });

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('本地演示数据更新入口', () => {
  it('keeps the control hidden when the local endpoint is unavailable', async () => {
    api.requestApi.mockResolvedValue({ success: false, http_status: 404, code: 'HTTP_404' });
    const wrapper = mountWidget();
    await flushPromises();
    expect(wrapper.find('button').exists()).toBe(false);
    wrapper.unmount();
  });

  it('does not reload when the initial status is already ready', async () => {
    api.requestApi.mockResolvedValue(ok(state('ready')));
    const wrapper = mountWidget();
    await flushPromises();
    expect(wrapper.text()).toContain('更新演示数据');
    expect(api.requestApi).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('sends one start request, serializes polling, retries transient 503, and stops polling on unmount', async () => {
    let finishStart;
    let finishPoll;
    api.requestApi.mockImplementation(({ url }) => {
      if (url.endsWith('/status') && api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/status')).length > 1) {
        return new Promise(resolve => { finishPoll = resolve; });
      }
      if (url.endsWith('/start')) return new Promise(resolve => { finishStart = resolve; });
      return Promise.resolve(ok(state()));
    });

    const wrapper = mountWidget();
    await flushPromises();
    const button = wrapper.findAll('button').find(item => item.text() === '更新演示数据');
    await button.trigger('click');
    await button.trigger('click');
    expect(api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/start'))).toHaveLength(1);

    finishStart(ok(state('queued')));
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    expect(api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/status'))).toHaveLength(2);
    expect(api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/status'))
      .every(([arg]) => arg.noMockFallback === true)).toBe(true);
    await vi.advanceTimersByTimeAsync(6000);
    expect(api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/status'))).toHaveLength(2);

    finishPoll({ success: false, http_status: 503, code: 'HTTP_503' });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    expect(api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/status'))).toHaveLength(3);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(12000);
    expect(api.requestApi.mock.calls.filter(([arg]) => arg.url.endsWith('/status'))).toHaveLength(3);
  });

  it('polls an asynchronous rollback until ready', async () => {
    const navigationAttempt = vi.spyOn(console, 'error').mockImplementation(() => {});
    let statusCalls = 0;
    api.requestApi.mockImplementation(({ url }) => {
      if (url.endsWith('/rollback')) return Promise.resolve(ok(state('activating', true)));
      statusCalls += 1;
      return Promise.resolve(ok(statusCalls === 1 ? state('idle', true) : state('ready', false)));
    });
    const wrapper = mountWidget();
    await flushPromises();
    const rollback = wrapper.findAll('button').find(item => item.text() === '回滚演示数据');
    expect(rollback).toBeTruthy();
    await rollback.trigger('click');
    await flushPromises();
    expect(api.requestApi).toHaveBeenCalledWith({ url: '/__demo_update/rollback', method: 'post' });
    expect(wrapper.text()).toContain('正在切换演示数据库');
    await vi.advanceTimersByTimeAsync(3000);
    await flushPromises();
    expect(statusCalls).toBe(2);
    expect(wrapper.text()).toContain('演示数据已更新');
    expect(navigationAttempt).toHaveBeenCalled();
    wrapper.unmount();
  });
});
