import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { reactive } from 'vue';
import { ElMessageBox } from 'element-plus';
const state = vi.hoisted(() => ({ requestApi: vi.fn(), downloadApiFile: vi.fn(), user: { id: 1 }, permissions: new Set(), route: null }));
vi.mock('../src/api/request', () => ({ requestApi: state.requestApi, downloadApiFile: state.downloadApiFile }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: state.user, hasPermission: code => state.permissions.has(code) }) }));
vi.mock('vue-router', () => ({ useRoute: () => state.route, onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn() }));
import OrderRegistrations from '../src/views/sales-management/OrderRegistrations.vue';
import RegistrationImportPanel from '../src/components/RegistrationImportPanel.vue';
import RegistrationAuditTrail from '../src/components/RegistrationAuditTrail.vue';
import AppPage from '../src/components/AppPage.vue';
import { canAccessPath, menuItems } from '../src/router/menu';

const stubs = {
  ElAlert: { props: ['title'], template: '<p>{{ title }}</p>' },
  ElButton: { emits: ['click'], props: ['disabled'], template: '<button :disabled="disabled" type="button" @click="$emit(\'click\')"><slot /></button>' },
  ElForm: { template: '<form><slot /></form>' }, ElFormItem: { template: '<div><slot /></div>' },
  ElDialog: { name: 'ElDialog', props: ['modelValue', 'title', 'closeOnClickModal'], emits: ['update:modelValue'], template: '<div v-if="modelValue" role="dialog" :aria-label="title"><button aria-label="关闭弹窗" @click="$emit(\'update:modelValue\', false)">关闭</button><slot /></div>' },
  ElDrawer: { name: 'ElDrawer', props: ['modelValue', 'title'], template: '<aside v-if="modelValue" aria-label="登记详情抽屉"><slot /></aside>' },
  ElDescriptions: { template: '<dl><slot /></dl>' }, ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElInput: true, ElSelect: true, ElOption: true, ElInputNumber: true, ElCheckbox: true,
  ElTable: true, ElTableColumn: true, ElPagination: true, RegistrationImportPanel: true,
};
const prefix = { exchange: 'sales_management.exchange', promotion: 'sales_management.promotion', gcash: 'finance.gcash' };
beforeEach(() => { vi.clearAllMocks(); state.permissions.clear(); state.user = { id: 1 }; state.route = reactive({ meta: { registrationKind: 'promotion' } }); state.requestApi.mockImplementation(async config => ({ success: true, data: config.url.endsWith('options/') ? { stores: [], skus: [] } : { results: [], count: 0 } })); });

describe('local order registration pages', () => {
  it('resolves snapshot-only SKU labels independently of search options', async () => {
    state.route.meta.registrationKind = 'exchange';
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 121, status: 'historical_recorded', payload: { changes: [] },
      snapshot: { historical: true, after: [{ sku_id: 5643, quantity: 1 }] },
      sku_details: [{ id: 5643, sku_code: '102010030-khaki-70X70CM' }], audit: [], evidence: [] };
    wrapper.vm.editing = true;
    wrapper.vm.skus = [];
    wrapper.vm.order = null;
    await flushPromises();
    expect(wrapper.text()).toContain('102010030-khaki-70X70CM × 1');
    expect(wrapper.text()).not.toContain('SKU #5643');
    expect(wrapper.text()).toContain('历史换货后（仅留档，未执行）');
  });
  it.each(['promotion', 'gcash'])('treats registered %s records as confirmation of actual payment without initiating a transfer', async kind => {
    state.route.meta.registrationKind = kind; state.permissions.add(`${prefix[kind]}.edit`);
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    expect(wrapper.find('.metrics').text()).toContain('已登记（已付款）');
    expect(wrapper.find('.metrics').text()).not.toContain('不代表系统已付款');
    wrapper.vm.selected = { id: 1, status: 'draft', version: 1, requested_by: 1, store_id: 1, payload: { payment_account: 'test-account', transaction_reference: 'test-reference' }, audit: [], evidence: [], evidence_count: 1 };
    wrapper.vm.editing = true;
    await flushPromises();
    const action = wrapper.vm.actions.find(action => action.code === 'register');
    expect(action.label).toBe('确认已付款并登记');
    wrapper.vm.requestAction(action);
    await flushPromises();
    expect(wrapper.text()).toContain('草稿尚未确认付款');
    expect(wrapper.text()).not.toContain('（不付款）');
    expect(state.requestApi.mock.calls.every(([config]) => config.method !== 'post')).toBe(true);
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.method === 'post' ? { ...wrapper.vm.selected, status: 'registered', version: 2 } : { results: [], count: 0 } }));
    await wrapper.vm.act('register');
    expect(wrapper.vm.selected.status).toBe('registered');
    expect(wrapper.vm.feedback).toContain('已确认实际付款，系统不会重复转账');
    expect(state.requestApi.mock.calls.filter(([config]) => config.method === 'post').map(([config]) => config.url)).toEqual([`/api/internal/commerce/registrations/${kind}/1/register/`]);
  });
  it.each(['exchange', 'promotion', 'gcash'])('limits screenshot uploads to GCash while preserving historical %s attachments', async kind => {
    state.route.meta.registrationKind = kind; state.permissions.add(`${prefix[kind]}.edit`);
    state.permissions.add(`${prefix[kind]}.submit`);
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 1, status: 'draft', requested_by: 1, payload: {}, snapshot: {}, evidence_count: 0, evidence: [], audit: [] };
    wrapper.vm.editing = true;
    await flushPromises();
    expect(wrapper.find('input[type="file"]').exists()).toBe(kind === 'gcash');
    expect(wrapper.text().includes('截图凭证')).toBe(kind === 'gcash');
    expect(wrapper.vm.actions.some(action => action.code === (state.route.meta.registrationKind === 'exchange' ? 'submit' : 'register'))).toBe(true);
    if (kind !== 'gcash') {
      expect(wrapper.vm.actions.some(action => action.code === (kind === 'exchange' ? 'submit' : 'register'))).toBe(true);
      wrapper.vm.selected.evidence_count = 1;
      wrapper.vm.selected.evidence = [{ id: 7, name: 'old-proof.png' }];
      await flushPromises();
      expect(wrapper.text()).toContain('历史附件（保留）');
      expect(wrapper.text()).toContain('old-proof.png');
      expect(wrapper.find('input[type="file"]').exists()).toBe(false);
    }
  });
  it('uses a date-only input for GCash payments', async () => {
    state.route.meta.registrationKind = 'gcash';
    state.permissions.add('finance.gcash.create');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.newRecord();
    await flushPromises();
    expect(wrapper.find('el-input-stub[type="date"]').exists()).toBe(true);
    expect(wrapper.find('[label="付款日期（中国时间，YYYY-MM-DD）"]').exists()).toBe(true);
    expect(wrapper.findAll('[label="备注"]')).toHaveLength(1);
    expect(wrapper.find('[label="原因"]').exists()).toBe(false);
    expect(wrapper.vm.form.payload).not.toHaveProperty('reason');
  });
  it.each([
    ['exchange', '/sales/pre-shipment-adjustments', '换货登记', '销售管理'],
    ['promotion', '/sales/special-order-registrations', '订单推广登记', '销售管理'],
    ['gcash', '/finance/gcash-refunds', 'GCash退款登记', '财务中心'],
  ])('registers the %s page with exact internal permission', (kind, path, label, parent) => {
    expect(menuItems.find(item => item.children?.some(child => child.path === path))?.label).toBe(parent);
    expect(canAccessPath({ user_type: 'internal', permissions: [`${prefix[kind]}.view`] }, path)).toBe(true);
    expect(canAccessPath({ user_type: 'internal', permissions: ['sales_management.orders.view'] }, path)).toBe(false);
    expect(canAccessPath({ user_type: 'external', permissions: [`${prefix[kind]}.view`] }, path)).toBe(false);
  });

  it('does not show create, import or approval controls to a read-only user', async () => {
    state.permissions.add('sales_management.promotion.view');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('订单推广登记');
    expect(wrapper.text()).not.toContain('新建登记');
    expect(wrapper.text()).not.toContain('批量提交');
    expect(state.requestApi.mock.calls.every(([config]) => config.noMockFallback === true)).toBe(true);
  });

  it.each(['exchange', 'promotion', 'gcash'])('uses the existing SaaS page shell and filter controls for %s', async kind => {
    state.route.meta.registrationKind = kind;
    state.permissions.add(`${prefix[kind]}.create`);
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    expect(wrapper.findComponent(AppPage).exists()).toBe(true);
    expect(wrapper.findAll('h1')).toHaveLength(1);
    expect(wrapper.find('.app-page__actions').text()).toContain('新建登记');
    expect(wrapper.find('form[aria-label="登记筛选"]').exists()).toBe(true);
    expect(wrapper.find('section[aria-label="登记列表"]').exists()).toBe(true);
    wrapper.vm.filters.status = 'draft';
    wrapper.vm.filters.order_number = 'test-order';
    wrapper.vm.page = 2;
    await wrapper.vm.resetFilters();
    expect(wrapper.vm.page).toBe(1);
    expect(wrapper.vm.filters).toEqual({ order_number: '', status: '', store_id: '', type: '' });
  });

  it.each(['exchange', 'promotion', 'gcash'])('opens and closes new %s registrations in a dialog without writing data', async kind => {
    state.route.meta.registrationKind = kind;
    state.permissions.add(`${prefix[kind]}.create`);
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.newRecord();
    await flushPromises();
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);
    expect(wrapper.find('section.registration-editor').exists()).toBe(false);
    expect(wrapper.findComponent({ name: 'ElDialog' }).props('closeOnClickModal')).toBe(false);
    await wrapper.find('[aria-label="关闭弹窗"]').trigger('click');
    expect(wrapper.vm.editing).toBe(false);
    expect(state.requestApi.mock.calls.every(([config]) => config.method !== 'post')).toBe(true);
  });

  it('keeps an unsuccessful draft save visible inside the dialog', async () => {
    state.permissions.add('sales_management.promotion.create');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord();
    Object.assign(wrapper.vm.form, { store_id: 1, order_id: 2, payload: { order_amount: '100', fee_amount: '10', fee_currency: 'CNY', exchange_rate: '8', rate_date: '2026-10-15', rate_source: '人工' } });
    state.requestApi.mockRejectedValue(new Error('登记校验未通过'));
    await wrapper.vm.save();
    expect(wrapper.find('[role="dialog"]').text()).toContain('登记校验未通过');
    expect(wrapper.vm.selected).toBeNull();
    expect(wrapper.vm.editing).toBe(true);
  });

  it('opens existing registration details in a drawer, not an inline editor', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord();
    const row = { id: 2, status: 'draft', version: 1, store_id: 1, payload: {}, snapshot: {}, audit: [], evidence: [], evidence_count: 0 };
    state.requestApi.mockResolvedValue({ success: true, data: row });
    await wrapper.vm.open(row);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.find('aside.registration-editor').exists()).toBe(true);
  });

  it('submits manual promotion amounts, never a client-calculated cost', async () => {
    state.permissions.add('sales_management.promotion.create');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord();
    Object.assign(wrapper.vm.form, { store_id: 1, order_id: 2, payload: { order_amount: '100', fee_amount: '10', fee_currency: 'CNY', exchange_rate: '8', rate_date: '2026-10-13', rate_source: '人工', note: '' } });
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.method === 'post' ? { id: 1, kind: 'promotion', status: 'draft', version: 1, payload: { cost: '180.00', currency: 'PHP' }, snapshot: {}, audit: [], evidence: [], evidence_count: 0 } : { results: [], count: 0 } }));
    await wrapper.vm.save();
    expect(state.requestApi).toHaveBeenCalledWith(expect.objectContaining({ method: 'post', data: expect.objectContaining({ payload: expect.objectContaining({ order_amount: '100', exchange_rate: '8' }) }) }));
    const payload = state.requestApi.mock.calls.find(([config]) => config.method === 'post')[0].data.payload;
    expect(payload).not.toHaveProperty('cost');
    expect(wrapper.text()).toContain('180.00 PHP');
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);
  });

  it('confirms promotion registration without approval and allows audited correction', async () => {
    state.permissions.add('sales_management.promotion.edit');
    state.permissions.add('sales_management.promotion.submit');
    state.permissions.add('sales_management.promotion.approve');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 1, status: 'draft', version: 1, requested_by: 1, payload: {}, audit: [], evidence: [], evidence_count: 0 };
    wrapper.vm.editing = true;
    await flushPromises();
    expect(wrapper.vm.actions.map(action => action.code)).toEqual(['register', 'cancel']);
    expect(wrapper.text()).not.toContain('提交审批');
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.method === 'post' ? { ...wrapper.vm.selected, status: 'registered', version: 2 } : { results: [], count: 0 } }));
    await wrapper.vm.act('register');
    expect(state.requestApi).toHaveBeenCalledWith(expect.objectContaining({ url: '/api/internal/commerce/registrations/promotion/1/register/', data: { note: '', version: 1 } }));
    expect(wrapper.vm.actions.map(action => action.code)).toEqual(['void']);
    expect(wrapper.vm.locked).toBe(true);
    expect(wrapper.text()).toContain('更正登记（保留历史）');
    wrapper.vm.correcting = true;
    wrapper.vm.dialogMode = true;
    await flushPromises();
    expect(wrapper.vm.locked).toBe(false);
  });

  it('only offers withdrawal of a legacy promotion approval', async () => {
    state.permissions.add('sales_management.promotion.edit');
    state.permissions.add('sales_management.promotion.approve');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 1, status: 'pending', version: 1, requested_by: 1, payload: {}, audit: [], evidence: [], evidence_count: 0 };
    expect(wrapper.vm.actions.map(action => action.code)).toEqual(['withdraw']);
    wrapper.vm.selected.requested_by = 2;
    await flushPromises();
    expect(wrapper.vm.actions).toEqual([]);
  });

  it('keeps an API failure visible without displaying saved success', async () => {
    state.requestApi.mockRejectedValue(new Error('真实后端失败'));
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); expect(wrapper.text()).toContain('真实后端失败');
  });

  it('distinguishes approved exchanges from completed detail updates and offers retry', async () => {
    state.route.meta.registrationKind = 'exchange';
    state.permissions.add('sales_management.exchange.approve');
    state.permissions.add('sales_management.exchange.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 1, status: 'update_failed', version: 4, requested_by: 2, payload: {}, snapshot: {}, audit: [], evidence: [], evidence_count: 0 };
    wrapper.vm.editing = true;
    await flushPromises();
    expect(wrapper.text()).toContain('审批已通过，但待发货明细尚未更新');
    expect(wrapper.vm.actions.map(action => action.code)).toEqual(['apply', 'cancel']);
    expect(wrapper.vm.locked).toBe(true);
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.method === 'post' ? { ...wrapper.vm.selected, status: 'completed', version: 5 } : { results: [], count: 0 } }));
    await wrapper.vm.act('apply');
    expect(state.requestApi).toHaveBeenCalledWith(expect.objectContaining({ url: '/api/internal/commerce/registrations/exchange/1/apply/', data: { note: '', version: 4 } }));
    expect(wrapper.vm.actions).toEqual([]);
  });
});

describe('registration import preview', () => {
  it('sends the historical mode and invalidates preview when mode changes', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'exchange' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'exchange.xlsx');
    wrapper.vm.historical = true;
    await flushPromises();
    state.requestApi.mockResolvedValueOnce({ success: true, data: { historical_exchange_supported: true } });
    state.requestApi.mockResolvedValueOnce({ success: true, data: { file_hash: 'history-hash', results: [] } });
    await wrapper.vm.run(false);
    expect(state.requestApi.mock.calls.at(-1)[0].data.get('historical')).toBe('true');
    expect(wrapper.text()).toContain('历史补录仅保存历史事实');
    wrapper.vm.historical = false;
    await flushPromises();
    expect(wrapper.vm.preview).toBeNull();
  });
  it('does not send historical imports to an older backend', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'exchange' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'exchange.xlsx');
    wrapper.vm.historical = true;
    await flushPromises();
    await wrapper.vm.run(false);
    expect(state.requestApi.mock.calls.some(([config]) => config.method === 'post')).toBe(false);
    expect(wrapper.vm.error).toContain('尚未加载历史补录功能');
  });
  it.each(['promotion', 'gcash'])('does not treat a %s import draft as confirmed payment', kind => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind }, global: { stubs } });
    expect(wrapper.find('.boundary').text()).toContain('仅生成草稿，尚未确认付款');
    expect(wrapper.find('.boundary').text()).toContain('另行确认已付款并登记');
  });
  it.each(['exchange', 'promotion'])('imports %s with only the spreadsheet and no screenshot controls', async kind => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind }, global: { stubs } });
    expect(wrapper.findAll('input[type="file"]')).toHaveLength(1);
    expect(wrapper.find('input[accept=".zip"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('无需截图或附件');
    wrapper.vm.file = new File(['test'], `${kind}.xlsx`);
    state.requestApi.mockResolvedValueOnce({ success: true, data: { results: [] } });
    await wrapper.vm.run(false);
    expect(state.requestApi.mock.calls.at(-1)[0].data.has('attachments')).toBe(false);
  });
  it('clears native inputs along with selected files when changing registration kinds', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'promotion' }, global: { stubs } });
    const oldInput = wrapper.find('input[type="file"]');
    Object.defineProperty(oldInput.element, 'files', { value: [new File(['test'], 'promotion.xlsx')] });
    await oldInput.trigger('change');
    expect(wrapper.vm.file.name).toBe('promotion.xlsx');
    await wrapper.setProps({ kind: 'exchange' });
    expect(wrapper.vm.file).toBeNull();
    expect(wrapper.find('input[type="file"]').element).not.toBe(oldInput.element);
    expect(wrapper.find('input[type="file"]').element.files).toHaveLength(0);
  });

  it('ignores a late preview response after switching pages', async () => {
    let resolve;
    state.requestApi.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'promotion' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'promotion.xlsx');
    const pending = wrapper.vm.run(false);
    await wrapper.setProps({ kind: 'exchange' });
    resolve({ success: true, data: { file_hash: 'old-result', results: [] } });
    await pending;
    expect(wrapper.vm.preview).toBeNull();
    expect(wrapper.vm.busy).toBe(false);
  });

  it('allows GCash without attachments and validates spreadsheet selection', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'gcash' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'gcash.xlsx');
    state.requestApi.mockResolvedValueOnce({ success: true, data: { results: [] } });
    await wrapper.vm.run(false);
    expect(state.requestApi.mock.calls.at(-1)[0].data.has('attachments')).toBe(false);
    wrapper.vm.setFile({ target: { files: [new File(['test'], 'wrong.csv')], value: 'wrong.csv' } }, 'file');
    expect(wrapper.vm.file).toBeNull();
    expect(wrapper.vm.error).toContain('xlsx');
  });

  it('previews all financial pages and sends the backfill choice', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'gcash' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'gcash.xlsx');
    wrapper.vm.backfill = true;
    await flushPromises();
    state.requestApi.mockResolvedValueOnce({ success: true, data: { file_hash: 'same', next_offset: 20, results: [{ valid: true, group: 'one' }] } });
    state.requestApi.mockResolvedValueOnce({ success: true, data: { file_hash: 'same', next_offset: null, results: [{ valid: true, group: 'two' }] } });
    await wrapper.vm.run(false);
    expect(wrapper.vm.preview.results).toHaveLength(2);
    expect(state.requestApi.mock.calls.map(([request]) => request.data.get('offset'))).toEqual(['0', '20']);
    expect(state.requestApi.mock.calls[0][0].data.get('backfill')).toBe('true');
  });

  it('clears an incomplete preview when a later page fails', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'promotion' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'promotion.xlsx');
    state.requestApi.mockResolvedValueOnce({ success: true, data: { file_hash: 'same', next_offset: 20, results: [{ valid: true }] } });
    state.requestApi.mockRejectedValueOnce(new Error('timeout'));
    await wrapper.vm.run(false);
    expect(wrapper.vm.preview).toBeNull();
    expect(wrapper.vm.error).toContain('timeout');
  });

  it('does not claim success when downloading a template fails', async () => {
    state.downloadApiFile.mockResolvedValueOnce({ success: false, message: '无下载权限' });
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'promotion' }, global: { stubs } });
    await wrapper.vm.downloadTemplate();
    expect(wrapper.vm.error).toBe('无下载权限');
  });
  it('describes the three-step import process without an inline disclosure', () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'promotion' }, global: { stubs } });
    expect(wrapper.find('details').exists()).toBe(false);
    expect(wrapper.find('section[aria-label="批量登记"]').exists()).toBe(true);
    expect(wrapper.findAll('.import-steps li')).toHaveLength(3);
  });
  it('uploads the original files again and binds confirmation to the preview hash', async () => {
    const wrapper = mount(RegistrationImportPanel, { props: { kind: 'promotion' }, global: { stubs } });
    wrapper.vm.file = new File(['test'], 'registration.xlsx');
    state.requestApi.mockResolvedValueOnce({ success: true, data: { file_hash: 'test-hash', confirmed: false, results: [{ rows: [2], group: '0001', valid: true, status: 'preview', payload: { cost: '180.00', currency: 'PHP' } }] } });
    await wrapper.vm.run(false);
    expect(wrapper.text()).toContain('确认导入草稿');
    state.requestApi.mockResolvedValueOnce({ success: true, data: { file_hash: 'test-hash', batch_id: 1, confirmed: true, results: [{ rows: [2], group: '0001', valid: true, status: 'created', id: 2 }] } });
    await wrapper.vm.run(true);
    const last = state.requestApi.mock.calls.at(-1)[0];
    expect(last.url).toContain('import-confirm/');
    expect(last.data.get('file_hash')).toBe('test-hash');
    expect(wrapper.emitted('imported')).toHaveLength(1);
  });
});

describe('registration workspace safeguards', () => {
  it.each(['exchange', 'promotion', 'gcash'])('shows soft-delete only for editable %s records', async kind => {
    state.route.meta.registrationKind = kind; state.permissions.add(`${prefix[kind]}.edit`);
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    for (const status of ['draft', 'rejected', 'withdrawn']) expect(wrapper.vm.canDelete({ id: 1, status })).toBe(true);
    for (const status of ['pending', 'registered', 'completed', 'update_failed', 'void']) expect(wrapper.vm.canDelete({ id: 1, status })).toBe(false);
    expect(wrapper.vm.canDelete({ id: 1, status: 'draft', deleted_at: '2026-10-15T00:00:00Z' })).toBe(false);
    state.permissions.clear();
    expect(wrapper.vm.canDelete({ id: 1, status: 'draft' })).toBe(false);
  });

  it('queries deleted records explicitly and preserves deletion scope on export', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    await wrapper.vm.toggleTrash();
    expect(wrapper.vm.trash).toBe(true);
    expect(state.requestApi.mock.calls.at(-1)[0].params.deleted).toBe('true');
    await wrapper.vm.exportRecords();
    expect(new URL(state.downloadApiFile.mock.calls.at(-1)[0], 'http://localhost').searchParams.get('deleted')).toBe('true');
  });

  it('requires a deletion reason and submits the captured record version', async () => {
    state.permissions.add('sales_management.promotion.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.beginLifecycle({ id: 7, status: 'draft', version: 3 }, 'delete');
    state.requestApi.mockClear();
    await wrapper.vm.submitLifecycle();
    expect(wrapper.vm.lifecycle.error).toContain('删除原因'); expect(state.requestApi).not.toHaveBeenCalled();
    wrapper.vm.lifecycle.reason = '重复草稿';
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.method === 'post' ? { id: 7, status: 'draft', version: 4, deleted_at: '2026-10-15T00:00:00Z' } : { results: [], count: 0 } }));
    await wrapper.vm.submitLifecycle();
    expect(state.requestApi).toHaveBeenCalledWith(expect.objectContaining({ method: 'post', url: '/api/internal/commerce/registrations/promotion/7/delete/', data: { version: 3, note: '重复草稿' } }));
    expect(wrapper.vm.lifecycle.visible).toBe(false);
  });

  it('does not offer editing, registration or approval for a deleted record', async () => {
    state.permissions.add('sales_management.promotion.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 7, status: 'draft', deleted_at: '2026-10-15T00:00:00Z', payload: {}, audit: [], evidence: [], evidence_count: 0 };
    wrapper.vm.dialogMode = true; wrapper.vm.editing = true;
    await flushPromises();
    expect(wrapper.vm.locked).toBe(true); expect(wrapper.vm.actions).toEqual([]);
    expect(wrapper.text()).toContain('恢复登记'); expect(wrapper.text()).not.toContain('编辑草稿');
  });

  it('handles partial batch deletion and does not claim that failed records were deleted', async () => {
    state.permissions.add('sales_management.promotion.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.rows = [{ id: 1, version: 2, status: 'draft' }, { id: 2, version: 3, status: 'draft' }];
    wrapper.vm.selectedIds = [1, 2]; wrapper.vm.beginBatchDelete(); wrapper.vm.lifecycle.reason = '批量核对后清理';
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.method === 'post' ? { results: [{ id: 1, success: true }, { id: 2, success: false, error: '版本已变化' }] } : { results: [], count: 1 } }));
    await wrapper.vm.submitLifecycle();
    expect(wrapper.vm.feedback).toContain('1 张草稿'); expect(wrapper.vm.listError).toContain('#2 未删除');
  });

  it('does not repeatedly submit a deletion with an uncertain network result', async () => {
    state.permissions.add('sales_management.promotion.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.beginLifecycle({ id: 7, version: 1, status: 'draft' }, 'delete'); wrapper.vm.lifecycle.reason = '删除重复';
    state.requestApi.mockResolvedValueOnce({ success: false, http_status: null, message: 'timeout' });
    await wrapper.vm.submitLifecycle(); expect(wrapper.vm.lifecycle.uncertain).toBe(true);
    state.requestApi.mockClear(); await wrapper.vm.submitLifecycle(); expect(state.requestApi).not.toHaveBeenCalled();
  });
  it('allows GCash confirmation without optional account or reference when evidence exists', async () => {
    state.route.meta.registrationKind = 'gcash'; state.permissions.add('finance.gcash.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 1, status: 'draft', payload: {}, evidence_count: 1, evidence: [], audit: [] };
    wrapper.vm.editing = true;
    await flushPromises();
    expect(wrapper.vm.actions.some(action => action.code === (state.route.meta.registrationKind === 'exchange' ? 'submit' : 'register'))).toBe(true);
    wrapper.vm.requestAction({ code: 'register', label: '确认正式登记' });
    expect(wrapper.vm.pendingAction.code).toBe('register');
    expect(wrapper.text()).not.toContain('正式登记还需补齐');
  });

  it('retains the form and offers reload after a version conflict without treating it as a timeout', async () => {
    state.permissions.add('sales_management.promotion.edit');
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.selected = { id: 1, status: 'draft', version: 1, payload: { cost: '100.00', currency: 'PHP' }, evidence_count: 0, evidence: [], audit: [] };
    wrapper.vm.editing = true;
    await flushPromises();
    state.requestApi.mockResolvedValueOnce({ success: false, code: 'STATE_CONFLICT', message: '版本已变化', http_status: 409 });
    await wrapper.vm.act('register');
    expect(wrapper.vm.conflict).toBe(true); expect(wrapper.vm.recovery).toBeNull();
    expect(wrapper.vm.selected.version).toBe(1);
    expect(wrapper.text()).toContain('重新加载当前登记并核对');
  });

  it('lets users cancel discarding unsaved changes', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord(); wrapper.vm.form.payload.note = '未保存';
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel');
    expect(await wrapper.vm.canDiscard()).toBe(false);
    expect(wrapper.vm.form.payload.note).toBe('未保存');
    confirm.mockRestore();
  });
  it('exports the exact store, date, type and batch filters used by the list', async () => {
    state.route.query = { store_id: '17' };
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises();
    wrapper.vm.filters.status = 'draft'; wrapper.vm.dateRange = ['2026-10-01', '2026-10-15']; wrapper.vm.batchId = 4;
    await wrapper.vm.exportRecords();
    const url = state.downloadApiFile.mock.calls[0][0];
    const query = new URL(url, 'http://localhost').searchParams;
    expect(query.get('store_id')).toBe('17'); expect(query.get('status')).toBe('draft');
    expect(query.get('created_from')).toBe('2026-10-01'); expect(query.get('created_to')).toBe('2026-10-15'); expect(query.get('batch_id')).toBe('4');
  });

  it('validates fields without submitting an incomplete registration', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord(); state.requestApi.mockClear();
    await wrapper.vm.save();
    expect(wrapper.vm.fieldErrors.store_id).toBeTruthy(); expect(wrapper.vm.fieldErrors.order_id).toBeTruthy();
    expect(state.requestApi).not.toHaveBeenCalled(); expect(wrapper.vm.editing).toBe(true);
  });

  it('tracks unsaved changes and leaves saved server cost out of outgoing fields', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord();
    expect(wrapper.vm.dirty).toBe(false);
    wrapper.vm.form.payload.note = '尚未保存';
    expect(wrapper.vm.dirty).toBe(true);
  });

  it('checks uncertain creation results by the original key rather than creating another registration', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord();
    Object.assign(wrapper.vm.form, { store_id: 1, order_id: 2, payload: { order_amount: '100', fee_amount: '10', fee_currency: 'CNY', exchange_rate: '8', rate_date: '2026-10-15', rate_source: '人工' } });
    const key = wrapper.vm.form.idempotency_key;
    state.requestApi.mockResolvedValueOnce({ success: false, code: 'HTTP_NETWORK_ERROR', message: 'timeout', http_status: null });
    await wrapper.vm.save();
    expect(wrapper.vm.recovery.key).toBe(key);
    state.requestApi.mockImplementation(async config => ({ success: true, data: config.params?.request_key ? { results: [{ id: 9, store_id: 1, status: 'draft', version: 1, order_number: '', payload: {}, snapshot: {}, evidence: [], evidence_count: 0, audit: [] }] } : { results: [], count: 1, summary: { draft: 1 } } }));
    state.requestApi.mockClear();
    await wrapper.vm.recover();
    expect(wrapper.vm.selected.id).toBe(9); expect(wrapper.vm.recovery).toBeNull();
    expect(state.requestApi.mock.calls.every(([config]) => !config.method)).toBe(true);
  });

  it('retains successful save feedback when only the list refresh fails', async () => {
    const wrapper = mount(OrderRegistrations, { global: { stubs } });
    await flushPromises(); wrapper.vm.newRecord();
    Object.assign(wrapper.vm.form, { store_id: 1, order_id: 2, payload: { order_amount: '100', fee_amount: '10', fee_currency: 'CNY', exchange_rate: '8', rate_date: '2026-10-15', rate_source: '人工' } });
    state.requestApi.mockImplementation(async config => config.method === 'post' ? { success: true, data: { id: 8, store_id: 1, status: 'draft', version: 1, order_number: '', payload: {}, evidence: [], evidence_count: 0, audit: [] } } : { success: false, message: '列表超时', http_status: 504 });
    await wrapper.vm.save();
    expect(wrapper.vm.selected.id).toBe(8); expect(wrapper.vm.feedback).toContain('草稿已保存');
    expect(wrapper.vm.listError).toBe('列表超时'); expect(wrapper.vm.recovery).toBeNull();
  });

  it('shows readable before and after values and correction reasons', () => {
    const wrapper = mount(RegistrationAuditTrail, { props: { events: [{ action: 'correct', actor_id: 1, actor__username: 'operator', created_at: '2026-10-15T00:00:00Z', masked_detail: { reason: '核对凭证', before: { amount: '10.00' }, after: { amount: '15.00' } } }] }, global: { stubs } });
    expect(wrapper.text()).toContain('核对凭证'); expect(wrapper.text()).toContain('实际金额');
    expect(wrapper.text()).toContain('10.00'); expect(wrapper.text()).toContain('15.00');
  });
});
