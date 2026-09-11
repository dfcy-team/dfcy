import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  actOnSyncAlertIncident: vi.fn(),
  disableSyncJob: vi.fn(),
  fetchSyncAlertIncidentRetryPreview: vi.fn(),
  fetchSyncAlertIncidents: vi.fn(),
  fetchSyncJobs: vi.fn(),
  retrySyncAlertIncident: vi.fn(),
  runSyncJobMock: vi.fn(),
  runSyncJob: vi.fn(),
  toggleSyncJob: vi.fn(),
}));
const routeState = vi.hoisted(() => ({
  query: {
    platform: 'shopee',
    api_type: 'marketplace',
    resource_type: 'platform_product',
    store_id: '1',
    subject: '新加坡示例店铺',
  },
}));
const router = vi.hoisted(() => ({ push: vi.fn() }));
const messages = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn(), error: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock('element-plus', async (importOriginal) => ({ ...(await importOriginal()), ElMessage: messages, ElMessageBox: { confirm } }));
const permissions = vi.hoisted(() => new Set([
  'integrations.view',
  'integrations.store.view',
  'masterdata.view',
  'integrations.run',
  'integrations.manage',
]));

vi.mock('../src/api/integrations', () => api);
vi.mock('../src/api/request', () => ({ useMock: true, requestApi: vi.fn() }));
vi.mock('../src/api/systemAdmin', () => ({ fetchUsers: vi.fn() }));
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: (permission) => permissions.has(permission) }),
}));
vi.mock('../src/utils/uiState', () => ({ statusFromApiResponse: () => 'forbidden' }));
vi.mock('vue-router', () => ({ useRoute: () => routeState, useRouter: () => router }));

import SyncJobList from '../src/views/integrations/SyncJobList.vue';

const stubs = {
  AppPage: { template: '<main><slot name="action" /><slot /></main>' },
  AppState: { template: '<div class="app-state"><slot /></div>' },
  MissingSyncJobsPreview: { template: '<section class="missing-preview" />' },
  'el-alert': { props: { title: String }, template: '<div class="alert"><strong>{{ title }}</strong><slot /></div>' },
  'el-button': { props: { disabled: Boolean, loading: Boolean }, emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-option': { template: '<option><slot /></option>' },
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': { template: '<div />' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-empty': { props: { description: String }, template: '<div class="empty">{{ description }}</div>' },
  'el-drawer': { props: { modelValue: Boolean }, template: '<div v-if="modelValue"><slot /></div>' },
  'el-descriptions': { template: '<div><slot /></div>' },
  'el-descriptions-item': { template: '<div><slot /></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<label><slot /></label>' },
  'el-input': { template: '<input />' },
};

describe('平台商品同步任务上下文闭环', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    confirm.mockResolvedValue('confirm');
    permissions.add('integrations.run_live_readonly');
    permissions.add('masterdata.view');
    permissions.add('integrations.view');
    permissions.add('integrations.store.view');
    permissions.add('integrations.manage');
    routeState.query = {
      platform: 'shopee',
      api_type: 'marketplace',
      resource_type: 'platform_product',
      store_id: '1',
      subject: '新加坡示例店铺',
    };
    api.fetchSyncJobs.mockResolvedValue({ success: true, data: { api_status: 'mock', summary: {}, results: [] } });
    api.fetchSyncAlertIncidents.mockResolvedValue({ success: true, data: [] });
  });

  it.each([
    [{ id: 9, is_enabled: false, status: 'idle', environment: 'production' }, '任务已停用'],
    [{ id: 9, is_enabled: true, status: 'disabled', environment: 'mock' }, '任务已停用'],
    [{ id: 9, is_enabled: true, status: 'idle', environment: 'production' }, '独立 Mock 任务'],
    [{ id: 9, is_enabled: true, status: 'idle', environment: 'mock', resource_type: 'sales_order' }, '独立 Mock 任务'],
    [{ id: 9, is_enabled: true, status: 'running', environment: 'mock', resource_type: 'mock_record' }, '正在运行'],
  ])('blocks invalid mock runs before submitting (%j)', async (row, reason) => {
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    expect(wrapper.vm.mockRunReason(row)).toContain(reason);
    await wrapper.vm.runAction(wrapper.vm.actionConfigs[0], row);
    expect(api.runSyncJobMock).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('allows only an enabled independent Mock task', async () => {
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    expect(wrapper.vm.mockRunReason({ id: 1, is_enabled: true, status: 'idle',
      environment: 'mock', resource_type: 'mock_record' })).toBe('');
    wrapper.unmount();
  });

  it('enables an existing job only after confirmation, without running it', async () => {
    api.toggleSyncJob.mockResolvedValue({ success: true });
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    await wrapper.vm.runAction(wrapper.vm.actionConfigs[2], { id: 9, is_enabled: false, status: 'idle' });
    expect(confirm).toHaveBeenCalled();
    expect(api.toggleSyncJob).toHaveBeenCalledWith(9, true);
    expect(api.runSyncJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('submits a real readonly run once, with confirmation and an idempotency key', async () => {
    api.runSyncJob.mockResolvedValue({ success: true, data: { accepted: true, task_id: 'fake-task' } });
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    const row = { id: 9, is_enabled: true, status: 'idle', environment: 'production' };
    await Promise.all([wrapper.vm.runAction(wrapper.vm.actionConfigs[3], row), wrapper.vm.runAction(wrapper.vm.actionConfigs[3], row)]);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(api.runSyncJob).toHaveBeenCalledTimes(1);
    expect(api.runSyncJob).toHaveBeenCalledWith(9, expect.any(String));
    expect(messages.success).toHaveBeenCalledWith(expect.stringContaining('不代表同步成功'));
    wrapper.unmount();
  });

  it.each(['disabled', 'permission', 'cancel'])('never submits a real run when blocked by %s', async (blocker) => {
    if (blocker === 'permission') permissions.delete('integrations.run_live_readonly');
    if (blocker === 'cancel') confirm.mockRejectedValue('cancel');
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    await wrapper.vm.runAction(wrapper.vm.actionConfigs[3], { id: 9, is_enabled: blocker !== 'disabled', status: 'idle', environment: 'production' });
    expect(api.runSyncJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('passes store context to tasks and incidents, then guides an authorized role back to the store API drawer', async () => {
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();

    expect(api.fetchSyncJobs).toHaveBeenCalledWith(expect.objectContaining({
      platform: 'shopee',
      api_type: 'marketplace',
      resource_type: 'platform_product',
      store_id: '1',
    }));
    expect(api.fetchSyncAlertIncidents).toHaveBeenCalledWith({ status: '', store_id: '1', resource_type: 'platform_product' });
    expect(wrapper.vm.productSyncContext).toBe(true);
    expect(wrapper.text()).toContain('新加坡示例店铺 · 平台商品同步任务');

    const action = wrapper.findAll('button').find((button) => button.text().includes('去店铺配置并创建商品同步任务'));
    expect(action.exists()).toBe(true);
    await action.trigger('click');
    expect(router.push).toHaveBeenCalledWith({
      path: '/master-data/stores',
      query: { store_id: '1', panel: 'api' },
    });
  });

  it('does not show the store configuration action without the required archive and API view permissions', async () => {
    permissions.delete('masterdata.view');
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();

    expect(wrapper.vm.canOpenStoreApiConfig).toBe(false);
    expect(wrapper.findAll('button').some((button) => button.text().includes('去店铺配置并创建商品同步任务'))).toBe(false);
  });

  it.each([{ results: [] }, { results: [{ id: 1 }] }])('keeps the task body beside the administrator preview for $results', async ({ results }) => {
    routeState.query = {};
    api.fetchSyncJobs.mockResolvedValue({ success: true, data: { api_status: 'mock', summary: {}, results } });
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    expect(wrapper.find('.missing-preview').exists()).toBe(true);
    expect(wrapper.find('[aria-label="同步任务健康摘要"]').exists()).toBe(true);
    expect(wrapper.find('.app-state').exists()).toBe(false);
    expect(wrapper.find('.empty').exists()).toBe(results.length === 0);
    wrapper.unmount();
  });

  it.each([true, false])('does not render a successful task body after failure (manager=%s)', async (manager) => {
    routeState.query = {};
    if (!manager) permissions.delete('integrations.manage');
    api.fetchSyncJobs.mockResolvedValue({ success: false, message: '无权限' });
    const wrapper = mount(SyncJobList, { global: { stubs } });
    await flushPromises();
    expect(wrapper.find('.app-state').exists()).toBe(true);
    expect(wrapper.find('[aria-label="同步任务健康摘要"]').exists()).toBe(false);
    expect(wrapper.find('.missing-preview').exists()).toBe(manager);
    wrapper.unmount();
  });
});
