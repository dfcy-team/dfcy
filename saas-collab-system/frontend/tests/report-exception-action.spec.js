import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const api = vi.hoisted(() => ({ createReportException: vi.fn() }));
const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('../src/api/reportCollaboration', () => api);
vi.mock('vue-router', () => ({ useRouter: () => nav }));

import ReportExceptionAction from '../src/views/reports/ReportExceptionAction.vue';

const config = { dataset: 'sales', dimensions: ['store_id', 'platform'], filters: { date_from: '2026-01-01' }, metrics: ['gross_sales'] };
const group = { store_id: 's1', platform: 'web', ignored: 'omit' };
const mountAction = () => mount(ReportExceptionAction, {
  props: { modelValue: true, config, group },
  global: { stubs: {
    'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
    'el-form': { template: '<form><slot /></form>' }, 'el-form-item': { template: '<div><slot /></div>' },
    'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
    'el-button': { props: ['loading', 'disabled'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
    'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' }
  } }
});

describe('ReportExceptionAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    let serial = 0;
    vi.stubGlobal('crypto', { randomUUID: () => `request-${++serial}` });
    api.createReportException.mockResolvedValue({ success: true, data: { id: 42 } });
  });

  it('sends every configured dimension, reuses the key on timeout retry, and navigates on success', async () => {
    api.createReportException.mockRejectedValueOnce(new Error('timeout'));
    const wrapper = mountAction();
    await wrapper.vm.submit();
    expect(wrapper.text()).toContain('超时');
    expect(nav.push).not.toHaveBeenCalled();
    await wrapper.vm.submit();
    const first = api.createReportException.mock.calls[0][0];
    const second = api.createReportException.mock.calls[1][0];
    expect(first.group).toEqual({ store_id: 's1', platform: 'web' });
    expect(first.config).toEqual(config);
    expect(second.request_key).toBe(first.request_key);
    expect(nav.push).toHaveBeenCalledWith('/workflow/exceptions/42');
    wrapper.unmount();
  });

  it('uses a fresh key after payload edits and suppresses concurrent submissions', async () => {
    let resolve;
    api.createReportException.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const wrapper = mountAction();
    const first = wrapper.vm.submit();
    await wrapper.vm.submit();
    expect(api.createReportException).toHaveBeenCalledTimes(1);
    resolve({ success: true, data: { id: 1 } });
    await first;
    wrapper.vm.title = '不同核查标题';
    await wrapper.vm.submit();
    expect(api.createReportException).toHaveBeenCalledTimes(2);
    expect(api.createReportException.mock.calls[1][0].request_key).not.toBe(api.createReportException.mock.calls[0][0].request_key);
    wrapper.vm.config.filters.date_from = '2026-02-01';
    await wrapper.vm.submit();
    expect(api.createReportException.mock.calls[2][0].request_key).not.toBe(api.createReportException.mock.calls[1][0].request_key);
    wrapper.unmount();
  });

  it('keeps the dialog open and does not navigate when creation fails', async () => {
    api.createReportException.mockRejectedValueOnce(new Error('服务器异常'));
    const wrapper = mountAction();
    await wrapper.vm.submit(); await flushPromises();
    expect(wrapper.vm.error).toContain('服务器异常');
    expect(wrapper.emitted('update:modelValue')).toBeUndefined();
    expect(nav.push).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain('SERVER_ERROR');
    wrapper.unmount();
  });
});
