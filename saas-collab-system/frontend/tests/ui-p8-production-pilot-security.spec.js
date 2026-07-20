import fs from 'node:fs';
import path from 'node:path';
import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mockP8Action, mockP8Detail, mockP8List, mockP8Patch, mockPilotControlRoom } from '../src/mock/pilot';
import AppState from '../src/components/AppState.vue';
import { canAccessPath } from '../src/router/menu';
import P8WorkflowWorkspace from '../src/views/pilot/P8WorkflowWorkspace.vue';

const pilotApi = vi.hoisted(() => ({
  createP8Resource: vi.fn(),
  fetchP8Resource: vi.fn(),
  fetchP8Resources: vi.fn(),
  patchP8Resource: vi.fn(),
  runP8Action: vi.fn()
}));
const routerContext = vi.hoisted(() => ({ route: { params: {} } }));
const authContext = vi.hoisted(() => ({ permissions: new Set() }));

vi.mock('../src/api/pilot', () => pilotApi);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: (permission) => authContext.permissions.has(permission) })
}));
vi.mock('vue-router', () => ({ useRoute: () => routerContext.route }));

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const successPage = (results = [{ id: 1, code: 'VER-DEMO', environment: 'pilot', category: 'browser_e2e', status: 'draft', version: 1 }]) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { count: results.length, next: null, previous: null, results, api_status: 'pending' }
});
const tableRowContext = { id: 1, code: 'VER-DEMO', environment: 'pilot', category: 'browser_e2e', status: 'draft', version: 1 };
const stubs = {
  AppPage: { template: '<main><slot name="action" /><slot /></main>' },
  ElButton: { template: '<button @click="$emit(\'click\', $event)"><slot /></button>' },
  ElSelect: { props: ['modelValue'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>' },
  ElOption: { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  ElTable: { props: ['data'], template: '<div class="table-stub"><slot /></div>' },
  ElTableColumn: {
    template: '<div><slot :row="row" /></div>',
    setup: () => ({ row: tableRowContext })
  },
  ElDrawer: { template: '<aside><slot /></aside>' },
  ElDialog: { template: '<section><slot /><slot name="footer" /></section>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElInput: { props: ['modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  ElPagination: { props: ['total', 'pageSize', 'currentPage'], template: '<button class="next-page" @click="$emit(\'current-change\', 2)">2</button>' },
  ElAlert: { template: '<div><slot /></div>' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElResult: {
    props: ['title', 'subTitle'],
    template: '<div><strong>{{ title }}</strong><span>{{ subTitle }}</span><slot name="extra" /></div>'
  }
};

function mountWorkspace(kind = 'verification') {
  return mount(P8WorkflowWorkspace, { props: { kind }, global: { stubs } });
}

describe('UI-P8 production pilot security readiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerContext.route.params = {};
    authContext.permissions = new Set();
    Object.assign(tableRowContext, { id: 1, code: 'VER-DEMO', environment: 'pilot', category: 'browser_e2e', status: 'draft', version: 1 });
    pilotApi.fetchP8Resources.mockResolvedValue(successPage());
    pilotApi.fetchP8Resource.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: successPage().data.results[0] });
    pilotApi.createP8Resource.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: {} });
    pilotApi.patchP8Resource.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: {} });
    pilotApi.runP8Action.mockResolvedValue({ success: true, code: 'OK', message: 'success', data: {} });
  });

  it('registers all routes with exact view permissions and denies external users', () => {
    const contracts = [
      ['/pilot/control-room', 'pilot.control.view'],
      ['/pilot/security-reviews', 'pilot.security_review.view'],
      ['/pilot/verification-runs', 'pilot.verification.view'],
      ['/pilot/performance-runs', 'pilot.performance.view'],
      ['/pilot/entry-decisions', 'pilot.entry.view']
    ];
    for (const [route, permission] of contracts) {
      expect(canAccessPath({ user_type: 'internal', permissions: [permission] }, route)).toBe(true);
      expect(canAccessPath({ user_type: 'internal', permissions: [] }, route)).toBe(false);
      expect(canAccessPath({ user_type: 'external', permissions: [permission] }, route)).toBe(false);
    }
  });

  it('uses only internal pilot endpoints and keeps real capability pending', () => {
    const api = read('src/api/pilot.js');
    expect(api).toContain('/api/internal/pilot/control-room/');
    for (const resource of ['security-reviews', 'verification-runs', 'performance-runs', 'entry-decisions']) expect(api).toContain(resource);
    expect(api).toContain("response.data.api_status = 'pending'");
    expect(api).not.toMatch(/\/api\/rpa\/|\/api\/finance\/|\/admin\/|deployNow|connectPlatform/);
  });

  it('keeps mock evidence stateful without external execution', () => {
    expect(mockPilotControlRoom().data.api_status).toBe('mock');
    expect(mockP8List('verification').data.results[0].status).toBe('draft');
    expect(mockP8Patch('verification', 1, { version: 1, target_alias: 'demo-target' })).toMatchObject({ success: true });
    expect(mockP8Action('verification', 1, 'submit', {}).data.status).toBe('submitted');
    expect(mockP8Detail('verification', 999)).toMatchObject({ success: false, http_status: 404 });
  });

  it('gates actions with exact plan review record and cancel permissions', () => {
    const page = read('src/views/pilot/P8WorkflowWorkspace.vue');
    for (const suffix of ['.plan', '.review', '.record', '.cancel']) expect(page).toContain(suffix);
    expect(page).toContain("row.status === 'draft'");
    expect(page).toContain("row.status === 'submitted'");
    expect(page).toContain("row.status === 'approved'");
  });

  it('renders complete loading error empty and detail states', () => {
    const pages = [read('src/views/pilot/ControlRoom.vue'), read('src/views/pilot/P8WorkflowWorkspace.vue')].join('\n');
    expect(pages).toContain("state = ref('loading')");
    expect(pages).toContain("'empty'");
    expect(pages).toContain('AppState');
    expect(pages).toContain('el-drawer');
  });

  it('does not expose real platform, deployment, credential, or money controls', () => {
    const pages = [
      'ControlRoom.vue', 'P8WorkflowWorkspace.vue', 'SecurityReviewWorkspace.vue',
      'VerificationRunWorkspace.vue', 'PerformanceRunWorkspace.vue', 'EntryDecisionWorkspace.vue'
    ].map((name) => read(`src/views/pilot/${name}`)).join('\n');
    expect(pages).not.toMatch(/password|api[_-]?secret|cookie|session|deployNow|executeRpa|transferMoney|purchaseOrderCreate/i);
    expect(pages).toContain('不连接真实平台');
  });

  it('renders mounted loading and empty states from real component state', async () => {
    pilotApi.fetchP8Resources.mockReturnValue(new Promise(() => {}));
    const loading = mountWorkspace();
    expect(loading.find('.app-state--loading').exists()).toBe(true);
    loading.unmount();

    pilotApi.fetchP8Resources.mockResolvedValue(successPage([]));
    const empty = mountWorkspace();
    await flushPromises();
    expect(empty.find('.app-state--empty').exists()).toBe(true);
  });

  it('renders a visible 404 for an invalid direct detail URL', async () => {
    routerContext.route.params = { id: '999999' };
    pilotApi.fetchP8Resource.mockResolvedValue({
      success: false,
      code: 'NOT_FOUND',
      message: 'Controlled pilot resource not found',
      data: null,
      http_status: 404
    });
    const wrapper = mountWorkspace();
    await flushPromises();
    expect(pilotApi.fetchP8Resource).toHaveBeenCalledWith('verification', '999999');
    expect(wrapper.find('.app-state--not_found').exists()).toBe(true);
    expect(wrapper.text()).toContain('Controlled pilot resource not found');
  });

  it.each([
    [401, 'AUTH_REQUIRED', 'unauthenticated'],
    [403, 'PERMISSION_DENIED', 'forbidden'],
    [404, 'NOT_FOUND', 'not_found'],
    [409, 'STATE_CONFLICT', 'conflict'],
    [422, 'VALIDATION_ERROR', 'invalid']
  ])('renders the mounted HTTP %s component state', async (httpStatus, code, expectedState) => {
    pilotApi.fetchP8Resources.mockResolvedValue({ success: false, code, message: `${code} demo`, data: null, http_status: httpStatus });
    const wrapper = mountWorkspace();
    await flushPromises();
    expect(wrapper.find(`.app-state--${expectedState}`).exists()).toBe(true);
    expect(wrapper.text()).toContain(`${code} demo`);
  });

  it('renders the mounted offline state without converting it to success', async () => {
    const original = navigator.onLine;
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    pilotApi.fetchP8Resources.mockResolvedValue({ success: false, code: 'HTTP_NETWORK_ERROR', message: 'offline demo', data: null });
    const wrapper = mountWorkspace();
    await flushPromises();
    expect(wrapper.find('.app-state--offline').exists()).toBe(true);
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: original });
  });

  it('renders the mounted stale evidence state', () => {
    const wrapper = mount(AppState, {
      props: { status: 'stale', detail: 'Demo evidence expired' },
      global: { stubs: { ElResult: stubs.ElResult, ElButton: stubs.ElButton } }
    });
    expect(wrapper.find('.app-state--stale').exists()).toBe(true);
    expect(wrapper.text()).toContain('Demo evidence expired');
  });

  it.each([
    ['pilot.verification.plan', 'draft', '提交评审'],
    ['pilot.verification.review', 'submitted', '人工批准'],
    ['pilot.verification.record', 'approved', '记录脱敏结果'],
    ['pilot.verification.cancel', 'draft', '取消计划']
  ])('shows the exact %s action for its valid state', async (permission, status, label) => {
    authContext.permissions = new Set([permission]);
    tableRowContext.status = status;
    pilotApi.fetchP8Resources.mockResolvedValue(successPage([{ ...tableRowContext }]));
    const wrapper = mountWorkspace();
    await flushPromises();
    expect(wrapper.text()).toContain(label);
  });

  it('reloads the real component after a successful workflow action', async () => {
    authContext.permissions = new Set(['pilot.verification.plan']);
    tableRowContext.status = 'draft';
    const wrapper = mountWorkspace();
    await flushPromises();
    const initialLoadCount = pilotApi.fetchP8Resources.mock.calls.length;
    await wrapper.findAll('button').find((button) => button.text() === '提交评审').trigger('click');
    await flushPromises();
    expect(pilotApi.runP8Action).toHaveBeenCalledWith('verification', 1, 'submit', {
      version: 1,
      reason: 'Submit controlled demo evidence for human review'
    });
    expect(pilotApi.fetchP8Resources.mock.calls.length).toBeGreaterThan(initialLoadCount);
    expect(wrapper.find('.app-state--loading').exists()).toBe(false);
  });

  it('passes pagination and filters to the list API', async () => {
    const wrapper = mountWorkspace();
    await flushPromises();
    await wrapper.findAll('select')[0].setValue('pilot');
    await wrapper.findAll('select')[1].setValue('draft');
    await wrapper.findAll('button').find((button) => button.text() === '查询').trigger('click');
    await flushPromises();
    expect(pilotApi.fetchP8Resources).toHaveBeenLastCalledWith('verification', {
      page: 1, page_size: 20, environment: 'pilot', status: 'draft'
    });
    await wrapper.find('.next-page').trigger('click');
    await flushPromises();
    expect(pilotApi.fetchP8Resources).toHaveBeenLastCalledWith('verification', {
      page: 2, page_size: 20, environment: 'pilot', status: 'draft'
    });
  });

  it('wires draft PATCH through the dedicated API and version contract', () => {
    const page = read('src/views/pilot/P8WorkflowWorkspace.vue');
    expect(page).toContain('patchP8Resource');
    expect(page).toContain('version: editForm.version');
    expect(page).toContain('编辑草稿');
  });

  it('hides plan and workflow actions from a mounted view-only workspace', async () => {
    authContext.permissions = new Set(['pilot.verification.view']);
    const wrapper = mountWorkspace();
    await flushPromises();
    expect(wrapper.text()).not.toContain('创建演示草稿');
    expect(wrapper.text()).not.toContain('提交评审');
    expect(wrapper.text()).not.toContain('人工批准');
    expect(wrapper.text()).not.toContain('记录脱敏结果');
    expect(wrapper.text()).not.toContain('取消计划');
  });
});
