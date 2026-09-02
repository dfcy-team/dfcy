import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const auditApi = vi.hoisted(() => ({
  exportOperationLogs: vi.fn(),
  fetchOperationLog: vi.fn(),
  fetchOperationLogs: vi.fn()
}));
const authContext = vi.hoisted(() => ({ canExport: true }));

vi.mock('../src/api/audit', () => auditApi);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => authContext.canExport })
}));

const stateStubs = {
  AppPage: { props: ['title'], template: '<main><h1>{{ title }}</h1><slot name="action" /><slot /></main>' },
  AppState: { props: ['status', 'detail'], template: '<div :class="`app-state--${status}`">{{ detail }}</div>' },
  ElAlert: { props: ['title'], template: '<div class="alert">{{ title }}</div>' },
  ElButton: { props: ['loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElDrawer: { props: ['modelValue'], template: '<aside><slot /></aside>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElInput: { template: '<input />' },
  ElPagination: { template: '<nav />' },
  ElTable: { template: '<div class="table"><slot /></div>' },
  ElTableColumn: true
};

const success = (results = [{ id: 1, operator_name: '审计员', module: 'system', action: 'user_update' }]) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { count: results.length, next: null, previous: null, results, api_status: 'connected' }
});

async function mountPage() {
  const { default: OperationLogList } = await import('../src/views/audit/OperationLogList.vue');
  return mount(OperationLogList, { global: { stubs: stateStubs } });
}

describe('operation audit page', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    authContext.canExport = true;
    auditApi.fetchOperationLogs.mockResolvedValue(success());
    auditApi.fetchOperationLog.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: { id: 1, before_data: {}, after_data: {} } });
    auditApi.exportOperationLogs.mockResolvedValue({ success: true, code: 'OK', message: '导出已开始。', data: null });
  });

  it('loads a paginated real API collection and renders audit controls', async () => {
    const wrapper = await mountPage();
    await flushPromises();

    expect(auditApi.fetchOperationLogs).toHaveBeenCalledWith({ page: 1, page_size: 20 });
    expect(wrapper.text()).toContain('日志审计');
    expect(wrapper.text()).toContain('导出 CSV');
    expect(wrapper.text()).not.toContain('Stage0');
  });

  it('maps a forbidden API response to a visible forbidden state', async () => {
    auditApi.fetchOperationLogs.mockResolvedValue({
      success: false,
      code: 'PERMISSION_DENIED',
      message: '无权访问',
      data: null,
      http_status: 403
    });
    const wrapper = await mountPage();
    await flushPromises();

    expect(wrapper.find('.app-state--forbidden').exists()).toBe(true);
    expect(wrapper.text()).toContain('无权访问');
  });

  it('hides export for a view-only operator and never calls the export API', async () => {
    authContext.canExport = false;
    const wrapper = await mountPage();
    await flushPromises();

    expect(wrapper.text()).not.toContain('导出 CSV');
    expect(auditApi.exportOperationLogs).not.toHaveBeenCalled();
  });
});
