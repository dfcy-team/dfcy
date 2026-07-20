import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AppState from '../src/components/AppState.vue';
import GovernanceCatalog from '../src/views/governance/GovernanceCatalog.vue';

const governanceApi = vi.hoisted(() => ({
  checkApiContractMock: vi.fn(),
  evaluateAssistantMock: vi.fn(),
  fetchApiContract: vi.fn(),
  fetchApiContracts: vi.fn(),
  fetchAssistant: vi.fn(),
  fetchAssistants: vi.fn()
}));
const routerContext = vi.hoisted(() => ({
  route: { params: {} },
  push: vi.fn(),
  replace: vi.fn()
}));
const authContext = vi.hoisted(() => ({ allowed: true }));

vi.mock('../src/api/governance', () => governanceApi);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => authContext.allowed })
}));
vi.mock('vue-router', () => ({
  useRoute: () => routerContext.route,
  useRouter: () => ({ push: routerContext.push, replace: routerContext.replace })
}));

const stateStubs = {
  ElResult: {
    props: ['title', 'subTitle'],
    template: '<div class="result-stub"><strong>{{ title }}</strong><span>{{ subTitle }}</span><slot name="extra" /></div>'
  },
  ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' }
};

const catalogStubs = {
  ...stateStubs,
  AppPage: { template: '<main><slot name="action" /><slot /></main>' },
  ElInput: { template: '<input />' },
  ElTable: { template: '<div class="table-stub"><slot /></div>' },
  ElTableColumn: true,
  ElPagination: {
    props: ['total', 'pageSize', 'currentPage'],
    emits: ['current-change'],
    template: '<button class="pagination-next" @click="$emit(\'current-change\', 2)">next</button>'
  },
  ElDrawer: { template: '<aside><slot /></aside>' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElAlert: { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' }
};

const successPage = (results = [{ id: 1, name: 'Readiness', status: 'sandbox' }]) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { count: results.length, next: null, previous: null, results, api_status: 'sandbox' }
});

function mountCatalog() {
  return mount(GovernanceCatalog, {
    props: { resource: 'api-contracts' },
    global: { stubs: catalogStubs }
  });
}

describe('UI-P7 mounted component state matrix', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerContext.route.params = {};
    authContext.allowed = true;
    governanceApi.fetchApiContracts.mockResolvedValue(successPage());
    governanceApi.fetchAssistants.mockResolvedValue(successPage());
    governanceApi.fetchApiContract.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: { id: 1 } });
    governanceApi.fetchAssistant.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: { id: 1 } });
  });

  it.each([
    ['loading', '正在加载'],
    ['empty', '暂无数据'],
    ['unauthenticated', '登录状态失效'],
    ['forbidden', '无权访问'],
    ['not_found', '资源不存在'],
    ['conflict', '状态已变化'],
    ['invalid', '信息未通过校验'],
    ['partial', '部分完成'],
    ['stale', '数据已过期'],
    ['offline', '服务暂不可用']
  ])('renders the %s application state', (status, title) => {
    const wrapper = mount(AppState, { props: { status }, global: { stubs: stateStubs } });
    expect(wrapper.find(`.app-state--${status}`).exists()).toBe(true);
    expect(wrapper.text()).toContain(title);
  });

  it('renders loading and empty from real catalog requests', async () => {
    governanceApi.fetchApiContracts.mockReturnValue(new Promise(() => {}));
    const loading = mountCatalog();
    expect(loading.find('.app-state--loading').exists()).toBe(true);
    loading.unmount();

    governanceApi.fetchApiContracts.mockResolvedValue(successPage([]));
    const empty = mountCatalog();
    await flushPromises();
    expect(empty.find('.app-state--empty').exists()).toBe(true);
  });

  it.each([
    [401, 'unauthenticated'],
    [403, 'forbidden'],
    [404, 'not_found'],
    [409, 'conflict'],
    [422, 'invalid']
  ])('maps HTTP %s to the visible %s state', async (httpStatus, expectedState) => {
    governanceApi.fetchApiContracts.mockResolvedValue({
      success: false,
      code: `HTTP_${httpStatus}`,
      message: `controlled ${httpStatus}`,
      data: null,
      http_status: httpStatus
    });
    const wrapper = mountCatalog();
    await flushPromises();
    expect(wrapper.find(`.app-state--${expectedState}`).exists()).toBe(true);
    expect(wrapper.text()).toContain(`controlled ${httpStatus}`);
  });

  it('renders an offline state for network failures', async () => {
    governanceApi.fetchApiContracts.mockResolvedValue({
      success: false,
      code: 'HTTP_NETWORK_ERROR',
      message: 'controlled offline',
      data: null,
      http_status: 0
    });
    const wrapper = mountCatalog();
    await flushPromises();
    expect(wrapper.find('.app-state--offline').exists()).toBe(true);
  });

  it('requests the selected page from a mounted catalog pagination control', async () => {
    governanceApi.fetchApiContracts.mockResolvedValue({
      ...successPage(),
      data: { ...successPage().data, count: 41 }
    });
    const wrapper = mountCatalog();
    await flushPromises();
    await wrapper.get('.pagination-next').trigger('click');
    await flushPromises();
    expect(governanceApi.fetchApiContracts).toHaveBeenLastCalledWith({ page: 2, page_size: 20, search: undefined });
  });

  it('hides contract check actions for a mounted view-only catalog', async () => {
    authContext.allowed = false;
    const wrapper = mountCatalog();
    await flushPromises();
    expect(wrapper.text()).not.toContain('合同检查');
    expect(governanceApi.checkApiContractMock).not.toHaveBeenCalled();
  });

  it('shows a visible 404 state when a direct governance detail does not exist', async () => {
    routerContext.route.params = { id: '999999' };
    governanceApi.fetchApiContract.mockResolvedValue({
      success: false,
      code: 'RESOURCE_NOT_FOUND',
      message: 'controlled resource not found',
      data: null,
      http_status: 404
    });
    const wrapper = mountCatalog();
    await flushPromises();
    expect(governanceApi.fetchApiContract).toHaveBeenCalledWith('999999');
    expect(wrapper.find('.app-state--not_found').exists()).toBe(true);
    expect(wrapper.text()).toContain('controlled resource not found');
  });
});
