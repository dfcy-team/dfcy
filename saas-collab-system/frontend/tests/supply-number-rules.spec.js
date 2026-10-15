import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { defineComponent, nextTick } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';

const api = vi.hoisted(() => ({ list: vi.fn(), preview: vi.fn(), save: vi.fn(), request: vi.fn() }));
vi.mock('../src/api/supplySettingsV2', () => ({ fetchSupplyNumberRules: api.list, previewSupplyNumberRule: api.preview, saveSupplyNumberRule: api.save }));
vi.mock('../src/api/supplyChainV2', () => ({ createIdempotencyKey: vi.fn(() => crypto.randomUUID()) }));
vi.mock('element-plus', async importOriginal => ({ ...await importOriginal(), ElMessage: { success: vi.fn() } }));
import SupplySettingsV2 from '../src/views/purchasing/SupplySettingsV2.vue';
import { useAuthStore } from '../src/stores/auth';
import { canAccessPath, menuItems } from '../src/router/menu';

const Slot = defineComponent({ template: '<section><slot/><slot name="footer"/></section>' });
const Alert = defineComponent({ props: ['title'], template: '<aside role="alert">{{title}}</aside>' });
const Dialog = defineComponent({ props: ['modelValue'], template: '<section v-if="modelValue"><slot/><slot name="footer"/></section>' });
const Button = defineComponent({ props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' });
const Input = defineComponent({ props: ['modelValue', 'disabled', 'type'], emits: ['update:modelValue'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\',$event.target.value)"/>' });
const stubs = { AppPage: Slot, 'el-table': Slot, 'el-table-column': true, 'el-tag': Slot, 'el-alert': Alert, 'el-button': Button, 'el-dialog': Dialog, 'el-form': Slot, 'el-form-item': Slot, 'el-input': Input, 'el-switch': Slot, 'el-select': Slot, 'el-option': true, 'el-input-number': Input };
const ok = data => ({ success: true, data });
const rule = (kind = 'purchase_order', extra = {}) => ({ kind, label: kind === 'purchase_order' ? '供应商采购单' : '入库单', version: 0, enabled: false, prefix: 'PO', date_format: 'YYYYMMDD', separator: '-', sequence_width: 4, reset_period: 'day', include_country: false, country_prefixes: {}, example: 'PO-20261015-<12位随机码>', legacy_description: '日期和随机码', history: [], ...extra });
const countries = [{ code: 'US', name: '美国' }, { code: 'PH', name: '菲律宾' }];
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function setup(canManage = true, permissions = ['supply.v2.view', 'supply.v2.manage']) {
  const auth = useAuthStore(); auth.setCurrentUser({ user_type: 'internal', permissions, action_permission_codes: permissions });
  api.list.mockResolvedValue(ok({ rules: [rule(), rule('inbound_order', { prefix: 'IN' })], countries, can_manage: canManage, business_date: '2026-10-15' }));
  const wrapper = mount(SupplySettingsV2, { global: { stubs, directives: { loading: () => {} } } });
  await flushPromises(); return { wrapper, auth };
}

describe('supply document number rules', () => {
  beforeEach(() => { vi.clearAllMocks(); setActivePinia(createPinia()); api.preview.mockResolvedValue(ok({ example: 'US-PO-20261015-0001', sequence: 1, business_date: '2026-10-15' })); });

  it('exposes the settings menu to internal accounts and excludes supplier accounts', () => {
    const supply = menuItems.find(item => item.label === '供应链协同');
    expect(supply.children.find(item => item.path === '/supply-chain/settings')?.label).toBe('供应链设置');
    const user = { user_type: 'internal', permissions: [], action_permission_codes: [], menu_permission_codes: ['menu.supply.supply_chain_settings.view'] };
    expect(canAccessPath(user, '/supply-chain/settings')).toBe(true);
    expect(canAccessPath({ ...user, user_type: 'external' }, '/supply-chain/settings')).toBe(false);
  });

  it('uses the selected country for preview and does not overwrite saved mappings while editing', async () => {
    const { wrapper } = await setup();
    const original = rule('purchase_order', { enabled: true, include_country: true, country_prefixes: { PH: 'FLB' } });
    wrapper.vm.editRule(original); await flushPromises();
    expect(api.preview).toHaveBeenLastCalledWith('purchase_order', expect.objectContaining({ country_code: 'US', include_country: true, country_prefixes: { PH: 'FLB' } }));
    wrapper.vm.form.country_prefixes.PH = 'PH'; wrapper.vm.previewCountry = 'PH'; await nextTick();
    expect(wrapper.vm.previewStale).toBe(true); expect(wrapper.vm.canSave).toBe(false);
    await wrapper.vm.runPreview();
    expect(api.preview).toHaveBeenLastCalledWith('purchase_order', expect.objectContaining({ country_code: 'PH' }));
    expect(original.country_prefixes.PH).toBe('FLB'); wrapper.unmount();
  });

  it('rejects a late preview for an old country and requires an up-to-date preview to save', async () => {
    const pending = deferred(); api.preview.mockReturnValueOnce(pending.promise);
    const { wrapper } = await setup();
    wrapper.vm.editRule(rule('purchase_order', { enabled: true, include_country: true }));
    wrapper.vm.previewCountry = 'PH'; wrapper.vm.reason = '增加国家前缀'; await nextTick();
    pending.resolve(ok({ example: 'US-PO-20261015-0001' })); await flushPromises();
    expect(wrapper.vm.preview).toBe(null); expect(wrapper.vm.canSave).toBe(false);
    await wrapper.vm.runPreview(); expect(wrapper.vm.canSave).toBe(true); wrapper.unmount();
  });

  it('does not save for a read-only scope or after authorization becomes stale', async () => {
    const { wrapper, auth } = await setup(false);
    wrapper.vm.editRule(rule()); await flushPromises(); wrapper.vm.reason = '试改';
    await wrapper.vm.saveRule(); expect(api.save).not.toHaveBeenCalled();
    api.list.mockResolvedValue(ok({ rules: [rule()], countries, can_manage: true })); await wrapper.vm.loadRules();
    auth.authorizationStale = true; await wrapper.vm.saveRule(); expect(api.save).not.toHaveBeenCalled(); wrapper.unmount();
  });

  it('keeps the same idempotency key on a failed-save retry and sends country configuration', async () => {
    const { wrapper } = await setup();
    const selected = rule('purchase_order', { enabled: true, include_country: true, country_prefixes: { PH: 'FLB' } });
    wrapper.vm.editRule(selected); await flushPromises(); wrapper.vm.reason = '统一国别单号';
    api.save.mockRejectedValueOnce(new Error('网络中断'));
    await wrapper.vm.saveRule(); const firstKey = api.save.mock.calls[0][2];
    expect(wrapper.text()).toContain('网络中断');
    api.save.mockResolvedValue(ok({ ...selected, version: 1, example: 'US-PO-20261015-0001' }));
    await wrapper.vm.saveRule();
    expect(api.save.mock.calls[1][2]).toBe(firstKey);
    expect(api.save.mock.calls[1][1]).toEqual(expect.objectContaining({ expected_version: 0, include_country: true, country_prefixes: { PH: 'FLB' }, reason: '统一国别单号' }));
    expect(api.save.mock.calls[1][1]).not.toHaveProperty('country_code');
    expect(wrapper.vm.rules[0].version).toBe(1); wrapper.unmount();
  });

  it('prevents an invalid date/reset combination from being previewed or saved', async () => {
    const { wrapper } = await setup(); wrapper.vm.editRule(rule()); await flushPromises();
    api.preview.mockClear(); wrapper.vm.form.enabled = true; wrapper.vm.form.date_format = 'YYYY'; wrapper.vm.reason = '无效日重置';
    await nextTick(); await wrapper.vm.runPreview(); await wrapper.vm.saveRule();
    expect(api.preview).not.toHaveBeenCalled(); expect(api.save).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('日期格式需要包含流水重置周期'); wrapper.unmount();
  });
});
