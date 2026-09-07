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
const permissions = vi.hoisted(() => new Set([
  'integrations.view',
  'integrations.store.view',
  'masterdata.view',
  'integrations.run',
  'integrations.manage',
]));

vi.mock('../src/api/integrations', () => api);
vi.mock('../src/api/request', () => ({ useMock: true }));
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
    permissions.add('masterdata.view');
    permissions.add('integrations.view');
    permissions.add('integrations.store.view');
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
});
