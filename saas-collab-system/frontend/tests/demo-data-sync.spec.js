import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  fetchDemoDataSyncOptions: vi.fn(), fetchDemoSyncEnvironments: vi.fn(), fetchDemoSyncBatches: vi.fn(),
  createDemoSyncBatch: vi.fn(), createDemoSyncEnvironment: vi.fn(), fetchDemoSyncBatch: vi.fn(),
  retryDemoSyncBatch: vi.fn(), downloadDemoSyncBatch: vi.fn(), updateDemoSyncEnvironmentStatus: vi.fn()
}));
const auth = vi.hoisted(() => ({ permissions: new Set(), hasPermission: vi.fn() }));
vi.mock('../src/api/demoDataSync', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));

import DemoDataSync from '../src/views/system/DemoDataSync.vue';
import { menuItems, findRouteCapability } from '../src/router/menu';

const ok = data => ({ success: true, code: 'OK', message: 'success', data });
const denied = { success: false, code: 'SERVICE_UNAVAILABLE', message: '同步服务连接失败', data: null };
const stubs = {
  AppPage: { template: '<main><slot /></main>' },
  ElTabs: { template: '<div><slot /></div>' },
  ElTabPane: { template: '<section><slot /></section>' },
  ElButton: { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  ElTable: { emits: ['row-click'], template: '<div><slot /></div>' },
  ElTableColumn: { template: '<div><slot :row="{}" /></div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElSelect: { template: '<div><slot /></div>' },
  ElOption: true,
  ElDatePicker: true,
  ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
  ElInput: true
};

function mountPage() { return mount(DemoDataSync, { global: { stubs } }); }

beforeEach(() => {
  vi.clearAllMocks();
  auth.permissions = new Set(['system.demo_sync.view', 'system.demo_sync.manage', 'system.demo_sync.run', 'system.demo_sync.download']);
  auth.hasPermission.mockImplementation(code => auth.permissions.has(code));
  api.fetchDemoDataSyncOptions.mockResolvedValue(ok({ enabled: true, resources: [{ code: 'orders', label: '订单' }], max_window_days: 31 }));
  api.fetchDemoSyncEnvironments.mockResolvedValue(ok({ results: [{ id: 4, name: 'Dev A' }] }));
  api.fetchDemoSyncBatches.mockResolvedValue(ok({ results: [] }));
  api.createDemoSyncBatch.mockResolvedValue(ok({ id: 'batch-1', status: 'queued' }));
  api.createDemoSyncEnvironment.mockResolvedValue(ok({ id: 6 }));
  api.updateDemoSyncEnvironmentStatus.mockResolvedValue(ok({ id: 4, active: false }));
});

describe('开发环境数据同步', () => {
  it('shows a failed options request as an error and never claims the service is merely unconfigured', async () => {
    api.fetchDemoDataSyncOptions.mockResolvedValue(denied);
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('同步服务连接失败');
    expect(wrapper.text()).not.toContain('部署未配置');
    wrapper.unmount();
  });

  it('keeps environment creation and task submission disabled when deployment is disabled', async () => {
    api.fetchDemoDataSyncOptions.mockResolvedValue(ok({ enabled: false, resources: [], max_window_days: 31 }));
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('部署未配置');
    expect(wrapper.findAll('button').some(button => button.text().includes('提交并排队') && button.element.disabled)).toBe(true);
    wrapper.vm.batchForm = { environment_id: 4, range: ['2026-10-01', '2026-10-02'] };
    await wrapper.vm.createBatch();
    expect(api.createDemoSyncBatch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('reports accepted work as queued and enforces the run permission', async () => {
    const wrapper = mountPage();
    await flushPromises();
    wrapper.vm.batchForm = { environment_id: 4, range: ['2026-10-01', '2026-10-02'] };
    await wrapper.vm.createBatch();
    await flushPromises();
    expect(api.createDemoSyncBatch).toHaveBeenCalledWith({ environment_id: 4, date_from: '2026-10-01', date_to: '2026-10-02' });
    expect(wrapper.text()).toContain('任务已提交并排队');
    wrapper.unmount();

    auth.permissions.delete('system.demo_sync.run');
    const readOnly = mountPage();
    await flushPromises();
    readOnly.vm.batchForm = { environment_id: 4, range: ['2026-10-01', '2026-10-02'] };
    await readOnly.vm.createBatch();
    expect(api.createDemoSyncBatch).not.toHaveBeenCalledTimes(2);
    readOnly.unmount();
  });

  it('allows managers to assign an owner and deactivate an environment; inactive environments cannot be selected', async () => {
    api.fetchDemoSyncEnvironments.mockResolvedValue(ok({ results: [
      { id: 4, name: 'Dev A', active: true }, { id: 5, name: 'Dev B', active: false }
    ] }));
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.vm.activeEnvironments.map(env => env.id)).toEqual([4]);
    wrapper.vm.envForm = { name: 'Dev C', owner_id: '17', resources: ['orders'], store_ids: '3', warehouse_ids: '8' };
    await wrapper.vm.createEnvironment();
    expect(api.createDemoSyncEnvironment).toHaveBeenCalledWith({ name: 'Dev C', owner_id: 17, resources: ['orders'], store_ids: [3], warehouse_ids: [8] });
    await wrapper.vm.toggleEnvironment({ id: 4, active: true });
    expect(api.updateDemoSyncEnvironmentStatus).toHaveBeenCalledWith(4, false);
    wrapper.unmount();
  });

  it('keeps environment controls disabled without manage permission and defaults the owner to the current user', async () => {
    auth.permissions.delete('system.demo_sync.manage');
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.vm.manageAccess.disabled).toBe(true);
    await wrapper.vm.toggleEnvironment({ id: 4, active: true });
    expect(api.updateDemoSyncEnvironmentStatus).not.toHaveBeenCalled();
    wrapper.unmount();

    auth.permissions.add('system.demo_sync.manage');
    const manager = mountPage();
    await flushPromises();
    manager.vm.envForm = { name: 'Mine', owner_id: '', resources: ['orders'], store_ids: '', warehouse_ids: '' };
    await manager.vm.createEnvironment();
    expect(api.createDemoSyncEnvironment).toHaveBeenCalledWith({ name: 'Mine', resources: ['orders'], store_ids: [], warehouse_ids: [] });
    manager.unmount();
  });

  it('does not poll again after unmount', async () => {
    api.fetchDemoSyncBatches.mockResolvedValue(ok({ results: [{ id: 'b1', status: 'running' }] }));
    const wrapper = mountPage();
    await flushPromises();
    expect(api.fetchDemoSyncBatches).toHaveBeenCalledTimes(1);
    vi.useFakeTimers();
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(16000);
    expect(api.fetchDemoSyncBatches).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('prevents overlapping batch-list requests', async () => {
    let finishRequest;
    api.fetchDemoSyncBatches.mockResolvedValueOnce(ok({ results: [] }));
    api.fetchDemoSyncBatches.mockImplementationOnce(() => new Promise(resolve => { finishRequest = resolve; }));
    const wrapper = mountPage();
    await flushPromises();
    const first = wrapper.vm.loadBatches();
    const second = wrapper.vm.loadBatches();
    expect(api.fetchDemoSyncBatches).toHaveBeenCalledTimes(2);
    finishRequest(ok({ results: [] }));
    await Promise.all([first, second]);
    wrapper.unmount();
  });

  it('registers the system management menu and view route permission', () => {
    const systemMenu = menuItems.find(item => item.label === '系统管理');
    expect(systemMenu.children.at(-1)).toMatchObject({ path: '/system/demo-data-sync', permissions: ['system.demo_sync.view'] });
    expect(findRouteCapability('/system/demo-data-sync')?.permissions).toContain('system.demo_sync.view');
  });
});
