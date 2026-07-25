import fs from 'node:fs';
import path from 'node:path';
import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { canAccessPath } from '../src/router/menu';
import ReleaseContractConsole from '../src/views/releases/ReleaseContractConsole.vue';

const releaseApi = vi.hoisted(() => ({
  confirmReleaseBuild: vi.fn(),
  createReleaseContract: vi.fn(),
  decideReleaseApproval: vi.fn(),
  fetchReleaseContract: vi.fn(),
  fetchReleaseContracts: vi.fn(),
  recordReleaseGate: vi.fn(),
  runReleaseAction: vi.fn()
}));
const authContext = vi.hoisted(() => ({ permissions: new Set() }));

vi.mock('../src/api/releaseContracts', () => releaseApi);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (permission) => authContext.permissions.has(permission)
  })
}));

const row = {
  id: 1001,
  contract_no: 'RC-TEST-1001',
  application_code: 'saas-miniapp',
  environment: 'test',
  commit_sha: 'a'.repeat(40),
  risk_level: 'medium',
  status: 'draft',
  version: 7,
  gate_summary: { required: 6, passed: 6, missing: [], failed: [], expired: [] },
  updated_at: '2026-07-24T00:00:00Z'
};
const successPage = (results = [row]) => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { count: results.length, results, api_status: 'mock' }
});

const stubs = {
  AppPage: {
    props: ['title', 'subtitle', 'boundaryNote'],
    template: '<main><h1>{{ title }}</h1><p>{{ boundaryNote }}</p><slot name="action" /><slot /></main>'
  },
  AppState: { template: '<div class="app-state">state</div>' },
  ElButton: { props: ['link'], template: '<button @click="$emit(\'click\', $event)"><slot /></button>' },
  ElSelect: { template: '<select><slot /></select>' },
  ElOption: { template: '<option />' },
  ElTag: { template: '<span><slot /></span>' },
  ElProgress: { template: '<span class="progress" />' },
  ElTable: { props: ['data'], template: '<div class="table"><slot /></div>' },
  ElTableColumn: {
    template: '<div><slot :row="row" /></div>',
    setup: () => ({ row })
  },
  ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
  ElDropdownMenu: { template: '<div><slot /></div>' },
  ElDropdownItem: { template: '<button><slot /></button>' },
  ElDrawer: { props: ['modelValue'], template: '<aside v-if="modelValue"><slot /></aside>' },
  ElDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /><slot name="footer" /></section>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElInput: { template: '<input />' },
  ElInputNumber: { template: '<input type="number" />' },
  ElRadioGroup: { template: '<div><slot /></div>' },
  ElRadio: { template: '<span><slot /></span>' },
  ElAlert: { template: '<div />' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElEmpty: { template: '<div />' },
  ElTimeline: { template: '<div><slot /></div>' },
  ElTimelineItem: { template: '<div><slot /></div>' }
};

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const mountConsole = () => mount(ReleaseContractConsole, { global: { stubs } });

describe('release contract console', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authContext.permissions = new Set(['release.contract.view']);
    releaseApi.fetchReleaseContracts.mockResolvedValue(successPage());
    releaseApi.fetchReleaseContract.mockResolvedValue({
      success: true,
      code: 'OK',
      message: 'success',
      data: { ...row, gate_results: [], approvals: [], audit_events: [] }
    });
  });

  it('registers an internal route with the exact view permission', () => {
    expect(canAccessPath(
      { user_type: 'internal', permissions: ['release.contract.view'] },
      '/releases/contracts'
    )).toBe(true);
    expect(canAccessPath(
      { user_type: 'internal', permissions: [] },
      '/releases/contracts'
    )).toBe(false);
    expect(canAccessPath(
      { user_type: 'external', permissions: ['release.contract.view'] },
      '/releases/contracts'
    )).toBe(false);
  });

  it('uses only the controlled internal release contract endpoints', () => {
    const api = read('src/api/releaseContracts.js');
    for (const suffix of ['contracts/', 'gates/', 'approvals/', 'build/', 'actions/']) {
      expect(api).toContain(suffix);
    }
    expect(api).toContain("'Idempotency-Key'");
    expect(api).not.toMatch(/api\.weixin|jscode2session|uploadCode|deployNow|AppSecret/i);
  });

  it('renders the list and hides every mutation from a view-only operator', async () => {
    const wrapper = mountConsole();
    await flushPromises();
    expect(wrapper.text()).toContain('发布合同操作台');
    expect(wrapper.text()).toContain('RC-TEST-1001');
    expect(wrapper.text()).not.toContain('新建发布合同');
    expect(wrapper.text()).not.toContain('录入门禁');
    expect(wrapper.text()).not.toContain('提交审批');
    expect(wrapper.text()).not.toContain('确认构建');
  });

  it('shows exact manager actions for a gate-complete draft', async () => {
    authContext.permissions = new Set([
      'release.contract.view',
      'release.contract.manage'
    ]);
    const wrapper = mountConsole();
    await flushPromises();
    expect(wrapper.text()).toContain('新建发布合同');
    expect(wrapper.text()).toContain('录入门禁');
    expect(wrapper.text()).toContain('提交审批');
  });

  it('loads contract detail through the dedicated API', async () => {
    const wrapper = mountConsole();
    await flushPromises();
    const detailButton = wrapper.findAll('button').find((button) => button.text() === '详情');
    await detailButton.trigger('click');
    await flushPromises();
    expect(releaseApi.fetchReleaseContract).toHaveBeenCalledWith(1001);
  });

  it('keeps platform execution outside the UI boundary', () => {
    const page = read('src/views/releases/ReleaseContractConsole.vue');
    expect(page).toContain('不直接上传代码');
    expect(page).toContain('不调用微信发布接口');
    expect(page).not.toMatch(/wx\.uploadFile|jscode2session|api\.weixin\.qq\.com|MINIAPP_APP_SECRET/);
  });
});
