import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import { defineComponent } from 'vue';

const api = vi.hoisted(() => ({
  requestApi: vi.fn(), downloadApiFile: vi.fn(), fetchPurchaseOrder:vi.fn(),downloadPurchaseExcel:vi.fn(),downloadPurchaseLabels:vi.fn(),
  fetchNotificationChannels: vi.fn(), fetchSupplierNotificationBinding: vi.fn(), saveSupplierNotificationBinding: vi.fn(),
  fetchPurchaseOrderNotification: vi.fn(), fetchSupplyNotification: vi.fn(), prepareSupplyNotification: vi.fn(),
  reconcileSupplyNotification: vi.fn(), retargetSupplyNotification: vi.fn(), retrySupplyNotificationPart: vi.fn(),
  verifySupplyNotificationPart: vi.fn(), downloadSupplyNotificationPart: vi.fn()
}));
vi.mock('../src/api/request', () => ({ requestApi: api.requestApi, downloadApiFile: api.downloadApiFile }));
vi.mock('../src/api/supplyChainV2', () => ({ createIdempotencyKey: () => 'stable-key',fetchPurchaseOrder:api.fetchPurchaseOrder,downloadPurchaseExcel:api.downloadPurchaseExcel,downloadPurchaseLabels:api.downloadPurchaseLabels }));
vi.mock('../src/api/supplyNotificationsV2', async (importOriginal) => {
  const original = await importOriginal();
  return { ...original,
    fetchNotificationChannels: api.fetchNotificationChannels, fetchSupplierNotificationBinding: api.fetchSupplierNotificationBinding,
    saveSupplierNotificationBinding: api.saveSupplierNotificationBinding, fetchPurchaseOrderNotification: api.fetchPurchaseOrderNotification,
    fetchSupplyNotification: api.fetchSupplyNotification, prepareSupplyNotification: api.prepareSupplyNotification,
    reconcileSupplyNotification: api.reconcileSupplyNotification, retargetSupplyNotification: api.retargetSupplyNotification,
    retrySupplyNotificationPart: api.retrySupplyNotificationPart, verifySupplyNotificationPart: api.verifySupplyNotificationPart,
    downloadSupplyNotificationPart: api.downloadSupplyNotificationPart
  };
});

import { createNotificationChannel } from '../src/api/supplyNotificationsV2';
import SupplierNotificationBindingV2 from '../src/components/supply-chain/SupplierNotificationBindingV2.vue';
import OrderNotificationV2 from '../src/components/supply-chain/OrderNotificationV2.vue';
import SupplyNotificationsV2 from '../src/views/purchasing/SupplyNotificationsV2.vue';
import { useAuthStore } from '../src/stores/auth';

const Stub = defineComponent({ props: ['disabled','modelValue','type','loading','label','value','title'], emits: ['click','update:modelValue','change','tab-change'], template: '<div><slot /><slot name="footer" /></div>' });
const Button = defineComponent({ props: ['disabled','loading','type'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>' });
const Input = defineComponent({ props: ['modelValue','disabled','type'], emits: ['update:modelValue'], template: '<textarea v-if="type===\'textarea\'" :disabled="disabled" :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/><input v-else :disabled="disabled" :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/>' });
const stubs = { 'el-button': Button, 'el-input': Input, 'el-tag': Stub, 'el-alert': Stub, 'el-skeleton': Stub, 'el-form': Stub, 'el-form-item': Stub, 'el-select': Stub, 'el-option': Stub, 'el-input-number': Stub, 'el-checkbox': Stub, 'el-radio-group': Stub, 'el-radio': Stub, 'el-dialog': Stub, 'el-empty': Stub };
function authWith(permissions = [], stale = false) { const auth = useAuthStore(); auth.setCurrentUser({ user_type: 'internal', permissions, action_permission_codes: permissions }); auth.authorizationStale = stale; return auth; }
const ok = (data) => ({ success: true, data });

describe('supply notifications v2', () => {
  beforeEach(() => {
    vi.clearAllMocks(); setActivePinia(createPinia());
    api.fetchPurchaseOrder.mockResolvedValue(ok(null)); api.downloadPurchaseExcel.mockResolvedValue(ok(null));api.downloadPurchaseLabels.mockResolvedValue(ok(null));
    api.fetchNotificationChannels.mockResolvedValue(ok([])); api.fetchSupplierNotificationBinding.mockResolvedValue(ok(null));
    api.fetchPurchaseOrderNotification.mockResolvedValue(ok(null)); api.fetchSupplyNotification.mockResolvedValue(ok(null));
    api.saveSupplierNotificationBinding.mockResolvedValue(ok({ version: 1 }));
  });

  it('sends idempotency key and reuses it after an unknown network result', async () => {
    api.requestApi.mockRejectedValueOnce(new Error('network timeout')).mockResolvedValueOnce(ok({ id: 7 }));
    await expect(createNotificationChannel({ name: 'A' })).rejects.toThrow('network timeout');
    await createNotificationChannel({ name: 'A' });
    const [first, second] = api.requestApi.mock.calls;
    expect(first[0].headers['Idempotency-Key']).toBe('stable-key');
    expect(second[0].headers['Idempotency-Key']).toBe(first[0].headers['Idempotency-Key']);
  });

  it('requires independent NOTIFY permission and blocks writes when authorization is stale', async () => {
    authWith(['supply.v2.manage']);
    const wrapper = mount(SupplierNotificationBindingV2, { props: { supplierId: 12 }, global: { stubs } });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain('无法自动拉取群成员');
    expect(wrapper.find('button:last-of-type').attributes('disabled')).toBeDefined();
    expect(api.saveSupplierNotificationBinding).not.toHaveBeenCalled();
    wrapper.unmount();
    authWith(['supply.v2.manage','supply.v2.notify'], true);
    expect(useAuthStore().authorizationStale).toBe(true);
    const stale = mount(SupplierNotificationBindingV2, { props: { supplierId: 12 }, global: { stubs } });
    await stale.vm.$nextTick();
    expect(stale.find('button:last-of-type').attributes('disabled')).toBeDefined();
    expect(api.saveSupplierNotificationBinding).not.toHaveBeenCalled();
  });

  it('keeps credential entry write-only and binding evidence is explicitly visible', async () => {
    authWith(['supply.v2.manage','supply.v2.notify']);
    api.fetchNotificationChannels.mockResolvedValue(ok([{ id: 1, name: '主通道', sender_name: '采购账号' }]));
    api.fetchSupplierNotificationBinding.mockResolvedValue(ok({ id: 1, version: 3, supplier_id: 9, channel_id: 1, channel_name: '主通道', sender_name: '采购账号', group_name: '供应商群', member_count: 8, verified: true, evidence: '人工核验记录' }));
    const wrapper = mount(SupplierNotificationBindingV2, { props: { supplierId: 9 }, global: { stubs } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.text()).toContain('已核验'); expect(wrapper.findAll('textarea').at(-1).element.value).toBe('人工核验记录');
    expect(wrapper.text()).not.toContain('robot_id');
    expect(wrapper.findAll('input[type="password"]')).toHaveLength(0);
  });

  it('shows manual content without a configured notification and reuses the loaded order', async()=>{
    authWith(['supply.v2.view']);
    api.fetchPurchaseOrderNotification.mockResolvedValue({success:false,message:'通知通道未接通'});
    const clipboard=vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:clipboard}});
    const wrapper=mount(OrderNotificationV2,{props:{orderId:72,order:{id:72,number:'PHPO72',supplier_url:'https://supplier-public.example/supplier/orders/72',notes:'internal-only-note',supplier_name:'测试供应商',country_name:'菲律宾',total_quantity:15,total_amount:'200.00',reference_number:'原始单72'}},global:{stubs}});
    await new Promise(resolve=>setTimeout(resolve,0));
    expect(wrapper.text()).toContain('人工转发内容');expect(wrapper.text()).toContain('总数量：15');expect(wrapper.text()).toContain('总金额：200.00');expect(wrapper.text()).toContain('备注单号：原始单72');
    expect(api.fetchPurchaseOrder).not.toHaveBeenCalled();expect(wrapper.text()).not.toContain('internal-only-note');expect(wrapper.find('a[href="https://supplier-public.example/supplier/orders/72"]').exists()).toBe(true);
    await wrapper.findAll('button').find(b=>b.text()==='复制通知内容').trigger('click');
    expect(clipboard).toHaveBeenCalledWith(expect.stringContaining('【采购订单】PHPO72'));expect(clipboard).toHaveBeenCalledWith(expect.stringContaining('https://supplier-public.example/supplier/orders/72'));
    await wrapper.findAll('button').find(b=>b.text()==='下载采购 Excel').trigger('click');
    expect(api.downloadPurchaseExcel).toHaveBeenCalledWith(72,'PHPO72');
    expect(api.prepareSupplyNotification).not.toHaveBeenCalled();expect(api.retrySupplyNotificationPart).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('distinguishes accepted from delivered and never offers direct retry for unknown parts', async () => {
    authWith(['supply.v2.manage','supply.v2.notify']);
    api.fetchPurchaseOrderNotification.mockResolvedValue(ok({ id: 22, version: 4 }));
    api.fetchSupplyNotification.mockResolvedValue(ok({ id: 22, version: 4, order_number: 'PO-22', supplier_name: '供方', status: 'awaiting_verification', total_quantity: 3, total_amount: '21.50', supplier_url: 'https://supplier.example/orders/22', summary: '订单内容', target_snapshot: { channel_name: '通知通道', sender_name: '采购号', group_name: '外部群' }, parts: [
      { id: 1, version: 2, kind: 'summary', status: 'accepted', text: '通知摘要', attempts: [{ id: 3, number: 1, outcome: 'accepted' }] },
      { id: 2, version: 3, kind: 'excel', status: 'unknown', object_name: 'PO-22.xlsx', attempts: [{ id: 4, number: 1, outcome: 'unknown' }] }
    ] }));
    const wrapper = mount(OrderNotificationV2, { props: { orderId: 22 }, global: { stubs } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.text()).toContain('工具已执行待核实'); expect(wrapper.text()).toContain('接口已受理'); expect(wrapper.text()).toContain('结果未知');
    expect(wrapper.text()).toContain('请先核对原群'); expect(wrapper.find('a[href="https://supplier.example/orders/22"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('通知摘要'); expect(wrapper.text()).not.toContain('重试已核实失败部件');
    expect(api.retrySupplyNotificationPart).not.toHaveBeenCalled();
  });

  it('offers retry only for failed parts and uses the failed part version', async () => {
    authWith(['supply.v2.manage','supply.v2.notify']);
    api.fetchPurchaseOrderNotification.mockResolvedValue(ok({ id: 31, version: 1 }));
    api.fetchSupplyNotification.mockResolvedValue(ok({ id: 31, version: 1, status: 'failed', parts: [{ id: 8, version: 6, kind: 'pdf', status: 'failed', attempts: [{ id: 9, number: 1, outcome: 'failed' }] }] }));
    const wrapper = mount(OrderNotificationV2, { props: { orderId: 31 }, global: { stubs } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.text()).toContain('重试已核实失败部件');
    expect(api.retrySupplyNotificationPart).not.toHaveBeenCalled();
    await wrapper.findAll('button').find((button) => button.text().includes('重试')).trigger('click');
    const reasonField = wrapper.findAll('textarea')[0];
    await reasonField.setValue('确认部件失败后重试');
    await wrapper.findAll('button').find((button) => button.text() === '确认').trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(api.retrySupplyNotificationPart).toHaveBeenCalledWith(31, 8, { expected_version: 6, reason: '确认部件失败后重试' });
    expect(SupplyNotificationsV2).toBeTruthy();
  });
});


it('shows one delivery notice and never treats an empty channel list as a disabled switch', async () => {
  setActivePinia(createPinia()); authWith([]);
  api.fetchNotificationChannels.mockResolvedValue(ok([]));
  const w=mount(SupplyNotificationsV2,{global:{stubs}}); await flushPromises();
  expect(w.vm.deliveryNote).toContain('无法确认');
  expect(w.vm.deliveryNote).not.toContain('尚未读取');
  expect(w.findAllComponents({name:'AppPage'}).length).toBeLessThanOrEqual(1);
  w.unmount();
});
