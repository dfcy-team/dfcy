import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessage, ElMessageBox } from 'element-plus';
import { inject, nextTick, provide, toRef } from 'vue';

const authContext = vi.hoisted(() => ({ allowed: true, manage: true }));
const api = vi.hoisted(() => ({
  bindWarehouseAuthorization: vi.fn(),
  checkIntegrationReadonlyConnection: vi.fn(),
  completeSyntheticStoreAuthorization: vi.fn(),
  createSyncJob: vi.fn(),
  fetchStoreAuthorizations: vi.fn(),
  fetchSubjectApiAccess: vi.fn(),
  fetchWarehouseAuthorizations: vi.fn(),
  refreshStoreAuthorization: vi.fn(),
  rebindWarehouseAuthorization: vi.fn(),
  revokeWarehouseAuthorization: vi.fn(),
  revokeStoreAuthorization: vi.fn(),
  startStoreAuthorization: vi.fn(),
}));

vi.mock('../src/api/integrations', () => api);
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (permission) => permission === 'integrations.manage'
      ? authContext.manage
      : authContext.allowed,
  }),
}));
vi.mock('../src/utils/actionAccess', () => ({
  getActionAccess: (auth, { permission }) => {
    const allowed = auth.hasPermission(permission);
    return {
      allowed,
      visible: true,
      disabled: !allowed,
      reason: allowed ? '' : `缺少权限：${permission}`,
    };
  },
}));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import SubjectApiAccessDialog from '../src/components/SubjectApiAccessDialog.vue';
import { mockSubjectApiAccess, mockStoreAuthorizations, mockWarehouseAuthorizations } from '../src/mock/integrations';

const TABLE_ROWS = Symbol('subject-api-table-rows');
const stubs = {
  'el-dialog': {
    props: { modelValue: Boolean, title: String },
    emits: ['opened'],
    mounted() {
      if (this.modelValue) this.$emit('opened');
    },
    template: '<div class="dialog"><slot name="header" /><slot /><slot name="footer" /></div>',
  },
  'el-alert': { props: { title: String }, template: '<div class="alert">{{ title }}<slot /></div>' },
  'el-skeleton': { template: '<div class="skeleton" />' },
  'el-tag': { props: { type: String }, template: '<span class="tag"><slot /></span>' },
  'el-button': {
    props: { disabled: Boolean, loading: Boolean, title: String, type: String },
    emits: ['click'],
    template: '<button :disabled="disabled" :title="title" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { template: '<label><slot /></label>' },
  'el-select': {
    props: { modelValue: [String, Number], disabled: Boolean },
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  'el-option': {
    props: { label: String, value: [String, Number] },
    template: '<option :value="value">{{ label }}</option>',
  },
  'el-input': {
    props: { modelValue: String, readonly: Boolean },
    template: '<input :value="modelValue" :readonly="readonly" />',
  },
  'el-table': {
    props: { data: { type: Array, default: () => [] } },
    setup(props) {
      provide(TABLE_ROWS, toRef(props, 'data'));
    },
    template: '<div class="table"><slot /></div>',
  },
  'el-table-column': {
    props: { label: String },
    setup() {
      return { rows: inject(TABLE_ROWS, toRef({ data: [] }, 'data')) };
    },
    template: '<div class="table-column" :data-label="label"><div v-for="row in rows" :key="row.id"><slot :row="row" /></div></div>',
  },
  'el-descriptions': { template: '<dl><slot /></dl>' },
  'el-descriptions-item': { props: { label: String }, template: '<div class="description"><dt>{{ label }}</dt><dd><slot /></dd></div>' },
};

function configureApi(subjectType = 'store') {
  const response = mockSubjectApiAccess(subjectType, 1);
  api.fetchSubjectApiAccess.mockResolvedValue(response);
  api.fetchStoreAuthorizations.mockResolvedValue(mockStoreAuthorizations({ store_id: 1 }));
  api.fetchWarehouseAuthorizations.mockResolvedValue(mockWarehouseAuthorizations({ warehouse_id: 1 }));
  api.createSyncJob.mockResolvedValue({ success: true, code: 'OK', data: { id: 999 } });
  api.startStoreAuthorization.mockResolvedValue({ success: true, data: { simulation_callback: { state: 'synthetic' } } });
  api.completeSyntheticStoreAuthorization.mockResolvedValue({ success: true, data: { simulation: true } });
  return response.data.subject;
}

async function mountDialog(subjectType = 'store') {
  const subject = configureApi(subjectType);
  const wrapper = mount(SubjectApiAccessDialog, {
    props: {
      modelValue: true,
      subjectType,
      row: subject,
    },
    global: { stubs },
  });
  await flushPromises();
  await nextTick();
  return wrapper;
}

describe('SubjectApiAccessDialog runtime closures', () => {
  beforeEach(() => {
    authContext.allowed = true;
    authContext.manage = true;
    vi.clearAllMocks();
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(true);
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'info').mockImplementation(() => undefined);
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined);
  });

  it('binds the manage permission to the rendered store sync button', async () => {
    authContext.allowed = true;
    authContext.manage = false;
    const wrapper = await mountDialog('store');
    const button = wrapper.findAll('button').find((item) => item.text().includes('创建同步任务'));
    expect(button.exists()).toBe(true);
    expect(button.attributes('disabled')).toBeDefined();
    await button.trigger('click');
    expect(api.createSyncJob).not.toHaveBeenCalled();
  });

  it('uses the selected registered resource in the sync-job payload', async () => {
    const wrapper = await mountDialog('store');
    const selector = wrapper.find('select.store-sync-resource-select');
    expect(selector.exists()).toBe(true);
    await selector.setValue('refund_return');
    const button = wrapper.findAll('button').find((item) => item.text().includes('创建同步任务'));
    await button.trigger('click');
    await flushPromises();
    expect(api.createSyncJob).toHaveBeenCalledWith(expect.objectContaining({
      integration_config_id: 1,
      store_authorization_id: 201,
      resource_type: 'refund_return',
      schedule_type: 'manual',
      is_enabled: true,
    }));
  });

  it('disables an active advertising binding and never sends an unsupported resource', async () => {
    const subject = configureApi('store');
    const base = mockSubjectApiAccess('store', 1).data;
    const marketplaceBinding = base.bindings.find((binding) => binding.status === 'active');
    api.fetchSubjectApiAccess.mockResolvedValue({
      success: true,
      code: 'OK',
      data: {
        ...base,
        api_types: ['advertising'],
        bindings: [{ ...marketplaceBinding, id: 701, api_type: 'advertising' }],
      },
    });
    const wrapper = mount(SubjectApiAccessDialog, {
      props: { modelValue: true, subjectType: 'store', row: subject },
      global: { stubs },
    });
    await flushPromises();
    await nextTick();

    const button = wrapper.findAll('button').find((item) => item.text() === '创建同步任务');
    expect(button.exists()).toBe(true);
    expect(button.attributes('disabled')).toBeDefined();
    expect(button.attributes('title')).toContain('广告 API 尚未注册');
    await button.trigger('click');
    await flushPromises();
    expect(api.createSyncJob).not.toHaveBeenCalled();
    expect(api.createSyncJob.mock.calls.some(([payload]) => payload?.resource_type === 'settlement_bill')).toBe(false);
  });

  it('renders a validated URL and keeps a manual copy action when popup and clipboard fail', async () => {
    const wrapper = await mountDialog('store');
    const authorizationUrl = 'https://auth.example.test/oauth/authorize?state=runtime';
    api.startStoreAuthorization.mockResolvedValue({ success: true, data: { authorization_url: authorizationUrl } });
    vi.spyOn(window, 'open').mockImplementation(() => null);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });

    const authorize = wrapper.findAll('button').find((item) => /授权.*Shopee/.test(item.text()));
    expect(authorize.exists()).toBe(true);
    await authorize.trigger('click');
    await flushPromises();

    const fallback = wrapper.find('.authorization-url-fallback');
    expect(fallback.exists()).toBe(true);
    expect(fallback.find('input').element.value).toBe(authorizationUrl);
    const copy = fallback.findAll('button').find((item) => item.text().includes('复制授权地址'));
    expect(copy.exists()).toBe(true);
    await copy.trigger('click');
    expect(ElMessage.warning).toHaveBeenCalledWith('复制失败，请手动选择并复制授权地址。');
  });

  it('loads history and opens the masked authorization detail from a rendered row', async () => {
    const wrapper = await mountDialog('store');
    const historyDetail = wrapper.findAll('button').find((item) => item.text() === '查看详情');
    expect(historyDetail.exists()).toBe(true);
    await historyDetail.trigger('click');
    await nextTick();
    expect(wrapper.vm.authorizationDetailOpen).toBe(true);
    expect(wrapper.vm.selectedAuthorizationDetail).toMatchObject({ status: 'expired' });
    expect(wrapper.text()).toContain('access_credential_hint=••••0203');
  });
});
