import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  requestApi: vi.fn(), updateSyncJob: vi.fn(), confirm: vi.fn(), success: vi.fn(),
}));
vi.mock('../src/api/request', () => ({ requestApi: api.requestApi }));
vi.mock('../src/api/integrations', () => ({ updateSyncJob: api.updateSyncJob }));
vi.mock('element-plus', async (importOriginal) => ({
  ...(await importOriginal()), ElMessage: { success: api.success }, ElMessageBox: { confirm: api.confirm },
}));

import SyncScheduleSettings from '../src/components/SyncScheduleSettings.vue';

const stubs = {
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-form': { props: ['disabled'], template: '<form><slot /></form>' },
  'el-form-item': { template: '<label><slot /></label>' },
  'el-select': { props: ['modelValue'], emits: ['update:modelValue'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>' },
  'el-option': { props: ['value'], template: '<option :value="value"><slot /></option>' },
  'el-input': { template: '<input />' }, 'el-input-number': { template: '<input />' },
  'el-date-picker': { template: '<input />' }, 'el-time-select': { template: '<input />' },
  'el-radio-group': { template: '<div><slot /></div>' }, 'el-radio': { template: '<span><slot /></span>' },
  'el-checkbox-group': { template: '<div><slot /></div>' }, 'el-checkbox': { template: '<span><slot /></span>' },
  'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
};

const recommendation = {
  available: true,
  values: { strategy_profile: 'efficient_v1', incremental_anchor: 'checkpoint', overlap_minutes: 12, query_mode: 'incremental', lookback_days: 3, execution_budget_seconds: 120, enabled: true, execution_mode: 'automatic', frequency: 'daily', schedule_type: 'daily' },
  notice: '检查点按成功查询上界继续。',
};
const orderJob = (extra = {}) => ({ id: 41, resource_type: 'sales_order', platform: 'shopee', schedule_type: 'manual', is_enabled: false, recommended_policy: recommendation, ...extra });
const mountPanel = (job = orderJob(), canManage = true) => mount(SyncScheduleSettings, { props: { job, canManage }, global: { stubs } });

describe('sync efficient policy runtime', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.confirm.mockResolvedValue('confirm');
    api.requestApi.mockResolvedValue({ success: true, data: { times: [], collection_range: { time_from: '2026-10-01T00:00:00+08:00', time_to: '2026-10-02T12:34:00+08:00' }, sync_policy: { anchor: 'checkpoint', notice: '检查点按成功查询上界继续。', bootstrap: false } } });
    api.updateSyncJob.mockResolvedValue({ success: true });
  });

  it('applies recommendation locally, previews then saves policy without changing task state or schedule', async () => {
    const wrapper = mountPanel();
    await wrapper.findAll('button').find(button => button.text().includes('应用推荐策略')).trigger('click');
    expect(api.requestApi).not.toHaveBeenCalled();
    await wrapper.findAll('button').find(button => button.text().includes('预览范围')).trigger('click');
    await flushPromises();
    expect(api.requestApi).toHaveBeenCalledOnce();
    const preview = api.requestApi.mock.calls[0][0];
    expect(preview.data).toMatchObject({ strategy_profile: 'efficient_v1', incremental_anchor: 'checkpoint', overlap_minutes: 12, execution_budget_seconds: 120, query_mode: 'incremental', lookback_days: 3 });
    expect(preview.data).not.toHaveProperty('enabled');
    expect(preview.data).not.toHaveProperty('schedule_type', 'daily');
    expect(wrapper.text()).toContain('2026');
    expect(wrapper.text()).toContain('检查点按成功查询上界继续。');
    const save = wrapper.findAll('button').find(button => button.text().includes('保存设置'));
    await save.trigger('click');
    await flushPromises();
    const payload = api.updateSyncJob.mock.calls[0][1];
    expect(payload).toMatchObject({ strategy_profile: 'efficient_v1', incremental_anchor: 'checkpoint', overlap_minutes: 12, execution_budget_seconds: 120, query_mode: 'incremental' });
    expect(payload).not.toHaveProperty('enabled');
    expect(payload).not.toHaveProperty('execution_mode');
    expect(payload).not.toHaveProperty('frequency');
    expect(payload.schedule_type).toBe('manual');
    wrapper.unmount();
  });

  it('does not expose or submit recommendation for read-only users', async () => {
    const wrapper = mountPanel(orderJob(), false);
    expect(wrapper.text()).not.toContain('应用推荐策略');
    await wrapper.findAll('button')[0].trigger('click');
    await wrapper.findAll('button')[1].trigger('click');
    await flushPromises();
    expect(api.requestApi).not.toHaveBeenCalled();
    expect(api.updateSyncJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('keeps legacy jobs compatible and omits the checkpoint field', async () => {
    const wrapper = mountPanel(orderJob({ strategy_profile: 'legacy', incremental_anchor: 'checkpoint', recommended_policy: { available: false } }));
    await wrapper.findAll('button').find(button => button.text().includes('预览范围')).trigger('click');
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('保存设置')).trigger('click');
    await flushPromises();
    const [payload] = api.updateSyncJob.mock.calls[0].slice(1);
    expect(payload.strategy_profile).toBe('legacy');
    expect(payload).not.toHaveProperty('incremental_anchor');
    wrapper.unmount();
  });

  it('offers efficient policy for settlement jobs and applies the recommended lookback budget', async () => {
    const financialJob = {
      id: 52, resource_type: 'settlement_bill', platform: 'shopee', schedule_type: 'manual', is_enabled: false,
      recommended_policy: { available: true, values: { strategy_profile: 'efficient_v1', incremental_anchor: 'lookback', lookback_days: 7, execution_budget_seconds: 120 }, notice: '按7天范围采集。' },
    };
    const wrapper = mountPanel(financialJob);
    expect(wrapper.text()).toContain('应用推荐策略');
    await wrapper.findAll('button').find(button => button.text().includes('应用推荐策略')).trigger('click');
    expect(api.requestApi).not.toHaveBeenCalled();
    await wrapper.findAll('button').find(button => button.text().includes('预览范围')).trigger('click');
    await flushPromises();
    expect(api.requestApi.mock.calls[0][0].data).toMatchObject({ strategy_profile: 'efficient_v1', incremental_anchor: 'lookback', lookback_days: 7, execution_budget_seconds: 120 });
    wrapper.unmount();
  });

  it('previews after switching to a mode where checkpoint is inapplicable and clears it to lookback', async () => {
    const wrapper = mountPanel(orderJob({ strategy_profile: 'efficient_v1', incremental_anchor: 'checkpoint', overlap_minutes: 5 }));
    const basis = wrapper.findAll('select').find(select => select.element.value === 'updated');
    await basis.setValue('created');
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('预览范围')).trigger('click');
    await flushPromises();
    expect(api.requestApi).toHaveBeenCalledOnce();
    expect(api.requestApi.mock.calls[0][0].data).toMatchObject({ collection_time_basis: 'created', incremental_anchor: 'lookback' });
    const save = wrapper.findAll('button').find(button => button.text().includes('保存设置'));
    expect(save.attributes('disabled')).toBeUndefined();
    await save.trigger('click');
    await flushPromises();
    expect(api.updateSyncJob.mock.calls[0][1]).toMatchObject({ collection_time_basis: 'created', incremental_anchor: 'lookback' });
    wrapper.unmount();
  });
});
