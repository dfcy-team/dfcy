import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { reactive } from 'vue';

const api = vi.hoisted(() => ({
  actOnHistorySyncBatch: vi.fn(),
  createHistorySyncBatch: vi.fn(),
  fetchHistorySyncBatches: vi.fn(),
}));
const permissions = vi.hoisted(() => ({ state: null }));
const messages = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock('../src/api/integrations', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: permission => permissions.state.has(permission) }) }));
vi.mock('element-plus', async importOriginal => ({ ...(await importOriginal()), ElMessage: messages, ElMessageBox: { confirm } }));

import ManualSyncBackfill from '../src/components/ManualSyncBackfill.vue';

permissions.state = reactive(new Set([
  'integrations.history.view', 'integrations.history.manage', 'integrations.run_live_readonly',
]));

const job = { id: 41, platform: 'shopee', resource_type: 'sales_order', environment: 'production', is_enabled: true, capability_state: 'ready', subject_name: '示例店铺' };
const stubs = {
  ElDrawer: { props: ['modelValue'], emits: ['close'], template: '<aside v-if="modelValue"><slot /></aside>' },
  ElDescriptions: { template: '<div><slot /></div>' },
  ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElDatePicker: { props: ['modelValue'], emits: ['update:modelValue'], template: '<input type="text" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  ElButton: { props: ['disabled', 'loading', 'title'], emits: ['click'], template: '<button :disabled="disabled" :title="title" @click="$emit(\'click\')"><slot /></button>' },
  ElAlert: { props: ['title'], template: '<div>{{ title }}</div>' },
  ElEmpty: { props: ['description'], template: '<div>{{ description }}</div>' },
  ElProgress: { props: ['percentage'], template: '<div>{{ percentage }}%</div>' },
};
function mountDrawer(props = {}) { return mount(ManualSyncBackfill, { props: { modelValue: true, job, ...props }, global: { stubs } }); }
async function enterDates(wrapper, start = '2026-01-01', end = '2026-01-10') {
  const pickers = wrapper.findAllComponents(stubs.ElDatePicker);
  pickers[0].vm.$emit('update:modelValue', start);
  pickers[1].vm.$emit('update:modelValue', end);
  await flushPromises();
}

describe('任务手动补采抽屉', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    permissions.state.clear();
    ['integrations.history.view', 'integrations.history.manage', 'integrations.run_live_readonly'].forEach(permission => permissions.state.add(permission));
    api.fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { batches: [] } });
    api.createHistorySyncBatch.mockResolvedValue({ success: true });
    api.actOnHistorySyncBatch.mockResolvedValue({ success: true });
    confirm.mockResolvedValue(true);
  });

  it('only reads task progress when opened and scopes the fetch to the pinned job', async () => {
    const wrapper = mountDrawer({ modelValue: false });
    expect(api.fetchHistorySyncBatches).not.toHaveBeenCalled();
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    expect(api.fetchHistorySyncBatches).toHaveBeenCalledWith({ sync_job_id: 41 });
    expect(wrapper.text()).toContain('#41 · 示例店铺');
    await wrapper.setProps({ modelValue: false });
    expect(api.fetchHistorySyncBatches).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('sends only the pinned task, selected range, and a stable idempotency key', async () => {
    api.createHistorySyncBatch.mockRejectedValueOnce(new Error('temporary failure')).mockResolvedValueOnce({ success: true });
    const wrapper = mountDrawer();
    await flushPromises();
    await enterDates(wrapper);
    const submit = wrapper.findAll('button').find(button => button.text() === '确认补采');
    await submit.trigger('click'); await flushPromises();
    await submit.trigger('click'); await flushPromises();
    expect(api.createHistorySyncBatch).toHaveBeenCalledTimes(2);
    const first = api.createHistorySyncBatch.mock.calls[0][0];
    expect(first).toMatchObject({ name: '手动补采任务 #41', job_ids: [41], start_date: '2026-01-01', end_date: '2026-01-10' });
    expect(Object.keys(first).sort()).toEqual(['end_date', 'idempotency_key', 'job_ids', 'name', 'start_date']);
    expect(api.createHistorySyncBatch.mock.calls[1][0].idempotency_key).toBe(first.idempotency_key);
    wrapper.unmount();
  });

  it.each([
    ['invalid calendar date', '2026-02-30', '2026-03-01'],
    ['future date', '2099-01-01', '2099-01-02'],
    ['reversed range', '2026-02-01', '2026-01-01'],
    ['overlong range', '2010-01-01', '2026-01-10'],
  ])('blocks submission for %s', async (_reason, start, end) => {
    const wrapper = mountDrawer();
    await flushPromises(); await enterDates(wrapper, start, end);
    expect(wrapper.text()).toMatch(/有效的 YYYY-MM-DD|北京时间今天|不能晚于|3660 天/);
    expect(wrapper.findAll('button').find(button => button.text() === '确认补采').attributes('disabled')).toBeDefined();
    expect(api.createHistorySyncBatch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('rechecks both permissions after the confirmation dialog resolves', async () => {
    let resolveConfirm;
    confirm.mockReturnValueOnce(new Promise(resolve => { resolveConfirm = resolve; }));
    const wrapper = mountDrawer(); await flushPromises(); await enterDates(wrapper);
    const submit = wrapper.findAll('button').find(button => button.text() === '确认补采');
    const pending = submit.trigger('click');
    permissions.state.delete('integrations.history.manage');
    resolveConfirm(true); await pending; await flushPromises();
    expect(api.createHistorySyncBatch).not.toHaveBeenCalled();
    expect(messages.error).toHaveBeenCalledWith(expect.stringContaining('权限、任务状态或当前任务已变化'));
    wrapper.unmount();
  });

  it('locks the submission while confirmation is pending', async () => {
    let resolveConfirm;
    confirm.mockReturnValueOnce(new Promise(resolve => { resolveConfirm = resolve; }));
    const wrapper = mountDrawer(); await flushPromises(); await enterDates(wrapper);
    const submit = wrapper.findAll('button').find(button => button.text() === '确认补采');
    const pending = submit.trigger('click');
    await submit.trigger('click');
    expect(confirm).toHaveBeenCalledOnce();
    expect(api.createHistorySyncBatch).not.toHaveBeenCalled();
    resolveConfirm(true); await pending; await flushPromises();
    expect(api.createHistorySyncBatch).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it.each(['closed', 'job changed', 'batch scope changed'])('does not retry after confirmation when context is %s', async change => {
    let resolveConfirm;
    confirm.mockReturnValueOnce(new Promise(resolve => { resolveConfirm = resolve; }));
    const approvedBatch = {
      id: 10, status: 'paused', total_segments: 2, success_segments: 1, failed_segments: 1, task_action_allowed: true,
      shops: [{ job_id: 41, resource_type: 'sales_order', status: 'paused', total_segments: 2, success_segments: 1, failed_segments: 1 }],
    };
    api.fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { batches: [approvedBatch] } });
    const wrapper = mountDrawer(); await flushPromises();
    const retry = wrapper.findAll('button').find(button => button.text() === '重试可恢复失败分段');
    const pending = retry.trigger('click');
    await retry.trigger('click');
    expect(confirm).toHaveBeenCalledOnce();
    if (change === 'closed') await wrapper.setProps({ modelValue: false });
    if (change === 'job changed') await wrapper.setProps({ job: { ...job, id: 42 } });
    if (change === 'batch scope changed') {
      api.fetchHistorySyncBatches.mockResolvedValueOnce({ success: true, data: { batches: [{
        ...approvedBatch, shops: [{ job_id: 99, resource_type: 'sales_order', status: 'paused' }],
      }] } });
      await wrapper.findAll('button').find(button => button.text() === '刷新').trigger('click');
      await flushPromises();
    }
    resolveConfirm(true); await pending; await flushPromises();
    expect(api.actOnHistorySyncBatch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('ignores stale progress responses after closing the drawer', async () => {
    let resolveLoad;
    api.fetchHistorySyncBatches.mockReturnValueOnce(new Promise(resolve => { resolveLoad = resolve; }));
    const wrapper = mountDrawer();
    await wrapper.vm.$nextTick();
    expect(api.fetchHistorySyncBatches).toHaveBeenCalledOnce();
    await wrapper.setProps({ modelValue: false });
    resolveLoad({ success: true, data: { batches: [{ id: 8, status: 'paused' }] } });
    await flushPromises();
    expect(wrapper.text()).not.toContain('历史补采 #8');
    wrapper.unmount();
  });

  it('shows legacy progress and disables whole-batch controls without server scope approval', async () => {
    api.fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { batches: [{
      id: 9, name: '旧多任务批次', status: 'paused', total_segments: 5, success_segments: 3, failed_segments: 1,
      shops: [{ job_id: 41, resource_type: 'sales_order', status: 'paused', total_segments: 5, success_segments: 3, failed_segments: 1, fetched_count: 22, recovery_hint: '重新授权后继续' }],
    }] } });
    const wrapper = mountDrawer(); await flushPromises();
    expect(wrapper.text()).toContain('3 成功 / 1 失败 / 5 总计');
    expect(wrapper.text()).toContain('恢复提示：重新授权后继续');
    const resume = wrapper.findAll('button').find(button => button.text() === '继续');
    const retry = wrapper.findAll('button').find(button => button.text() === '重试可恢复失败分段');
    expect(resume.attributes('disabled')).toBeDefined();
    expect(resume.attributes('title')).toContain('包含其他任务');
    expect(retry.attributes('disabled')).toBeDefined();
    expect(retry.attributes('title')).toContain('包含其他任务');
    await resume.trigger('click');
    await retry.trigger('click');
    expect(api.actOnHistorySyncBatch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('allows only server-approved single-task batch controls', async () => {
    api.fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { batches: [{
      id: 10, status: 'paused', total_segments: 2, success_segments: 1, failed_segments: 1, task_action_allowed: true,
      shops: [{ job_id: 41, resource_type: 'sales_order', status: 'paused', total_segments: 2, success_segments: 1, failed_segments: 1 }],
    }] } });
    const wrapper = mountDrawer(); await flushPromises();
    const resume = wrapper.findAll('button').find(button => button.text() === '继续');
    expect(resume.attributes('disabled')).toBeUndefined();
    await resume.trigger('click'); await flushPromises();
    expect(api.actOnHistorySyncBatch).toHaveBeenCalledWith(10, 'resume');
    wrapper.unmount();
  });

  it('keeps progress visible but disables creation when a mutation permission is missing', async () => {
    permissions.state.delete('integrations.run_live_readonly');
    api.fetchHistorySyncBatches.mockResolvedValue({ success: true, data: { batches: [{
      id: 7, name: '旧暂停补采', status: 'paused', total_segments: 3, success_segments: 1, failed_segments: 1,
      shops: [{ job_id: 41, resource_type: 'sales_order', status: 'paused', total_segments: 3, success_segments: 1, failed_segments: 1 }],
    }] } });
    const wrapper = mountDrawer(); await flushPromises();
    expect(wrapper.text()).toContain('缺少历史补采管理或真实只读执行权限');
    expect(wrapper.text()).toContain('旧暂停补采');
    expect(wrapper.findAll('button').find(button => button.text() === '确认补采').attributes('disabled')).toBeDefined();
    wrapper.unmount();
  });

  it('does not fetch or display history without history.view permission', async () => {
    permissions.state.delete('integrations.history.view');
    const wrapper = mountDrawer(); await flushPromises();
    expect(api.fetchHistorySyncBatches).not.toHaveBeenCalled();
    expect(wrapper.find('[aria-label="该任务的历史补采进度"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    { platform: 'lazada' },
    { environment: 'mock' },
    { is_enabled: false },
    { capability_state: 'blocked' },
    { schedule_state: 'queued' },
  ])('blocks a task that is unsupported, readonly-ineligible, or busy (%j)', async overrides => {
    const wrapper = mountDrawer({ job: { ...job, ...overrides } }); await flushPromises();
    await enterDates(wrapper);
    const submit = wrapper.findAll('button').find(button => button.text() === '确认补采');
    expect(submit.attributes('disabled')).toBeDefined();
    expect(api.createHistorySyncBatch).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
