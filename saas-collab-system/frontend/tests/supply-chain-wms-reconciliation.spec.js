import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const mocks = vi.hoisted(() => ({ requestApi: vi.fn(), hasPermission: true }));
vi.mock('../src/api/request', () => ({ requestApi: mocks.requestApi }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ authorizationStale: false, hasPermission: () => mocks.hasPermission }) }));
vi.mock('element-plus', async (original) => ({ ...await original(), ElMessageBox: { confirm: vi.fn() } }));

import * as api from '../src/api/supplyLogisticsV2';
import SupplyLogisticsV2 from '../src/views/purchasing/SupplyLogisticsV2.vue';
const requestApi = mocks.requestApi;

const stubs = {
  AppPage: { template: '<main><slot name="action"/><slot/></main>' },
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled||loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p>{{title}}</p>' },
  'el-tabs': { template: '<div><slot/></div>' }, 'el-tab-pane': { template: '<section><slot/></section>' },
  'el-input': { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\',$event.target.value)"/>' },
  'el-select': { props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<select><slot/></select>' },
  'el-option': { template: '<option/>' }, 'el-table': { props: ['data'], template: '<div><slot/></div>' },
  'el-table-column': { template: '<div><slot :row="{}"/></div>' }, 'el-pagination': { template: '<nav/>' },
  'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
  'el-drawer': { props: ['modelValue'], template: '<aside v-if="modelValue"><slot/><slot name="footer"/></aside>' },
  'el-form-item': { template: '<label><slot/></label>' }, 'el-descriptions': { template: '<div><slot/></div>' },
  'el-descriptions-item': { template: '<div><slot/></div>' }, 'el-date-picker': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/>' },
  'el-input-number': { props: ['modelValue', 'min', 'max', 'disabled'], emits: ['update:modelValue'], template: '<input type="number" :value="modelValue" :min="min" :max="max" :disabled="disabled" @input="$emit(\'update:modelValue\',Number($event.target.value))"/>' },
  'el-radio': { template: '<input type="radio"/>' },
  CostSettlementLinkV2: true, DocumentSkuV2: true, DocumentProductImageV2: true,
  DispatchProductLinesV2: true, FreightPlanFieldsV2: true
};

const batch = { id: 7, number: 'DB-7', version: 4, status: 'active', stage: 'departed', country_code: 'US',
  freight_company_id: 9, freight_company_name: 'Forwarder', freight_number: 'F-7', shipments: [], logistics_dates: {} };
const inbound = { id: 12, number: 'IN-12', batch_number: 'DB-7', country_code: 'US', warehouse_id: 3,
  warehouse_name: 'US warehouse', version: 2, status: 'confirmed', lines: [{ id: 31, sku: 'SKU-1', received_quantity: 5 }] };

function mountPage() {
  return mount(SupplyLogisticsV2, { global: { stubs, directives: { loading: () => {} } } });
}

describe('logistics ETA and WMS reconciliation API', () => {
  beforeEach(() => requestApi.mockReset().mockResolvedValue({ success: true, data: [] }));

  it('uses versioned ETA and scoped WMS routes with idempotency keys on writes', async () => {
    await api.updateDispatchExpectedWarehouseDate(7, {
      expected_version: 4, expected_warehouse_date: '2026-11-08', reason: '船期调整'
    }, 'eta-key');
    await api.fetchWmsReconciliation(12);
    await api.fetchWmsCandidates(12, { inbound_line_id: 31 });
    await api.createWmsAllocation(12, {
      inbound_line_id: 31, wms_line_id: 99, quantity: 3, notes: '核对'
    }, 'allocation-key');
    await api.deactivateWmsAllocation(12, 45, {
      expected_version: 2, reason: '重复扫描'
    }, 'deactivate-key');

    const calls = requestApi.mock.calls.map(([request]) => request);
    expect(calls.map(({ method, url }) => [method, url])).toEqual([
      ['post', '/api/internal/supply-chain/v2/dispatch-batches/7/expected-warehouse-date/'],
      ['get', '/api/internal/supply-chain/v2/inbound-orders/12/wms-reconciliation/'],
      ['get', '/api/internal/supply-chain/v2/inbound-orders/12/wms-candidates/'],
      ['post', '/api/internal/supply-chain/v2/inbound-orders/12/wms-allocations/'],
      ['post', '/api/internal/supply-chain/v2/inbound-orders/12/wms-allocations/45/deactivate/']
    ]);
    expect(calls[2].params).toEqual({ inbound_line_id: 31 });
    expect(calls[0].headers['Idempotency-Key']).toBe('eta-key');
    expect(calls[3].headers['Idempotency-Key']).toBe('allocation-key');
    expect(calls[4].headers['Idempotency-Key']).toBe('deactivate-key');
  });

  it('keeps empty WMS candidates non-editable with a valid numeric range and no allocation write', async () => {
    mocks.requestApi.mockImplementation(async (request) => {
      if (!request?.url) return { success: true, data: [] };
      if (request.url.endsWith('/dispatch-options/')) return { success: true, data: { countries: [], freight_companies: [], warehouses: [] } };
      if (request.url.endsWith('/inbound-orders/12/')) return { success: true, data: inbound };
      return { success: true, data: [] };
    });
    const page = mountPage();
    await flushPromises();
    await page.vm.openInbound(inbound);
    await page.vm.openWmsCandidates({ inbound_line_id: 31, remaining_quantity: 5 });
    const quantity = page.find('input[type="number"][max="0"]');
    expect(quantity.attributes('min')).toBe('0');
    expect(quantity.element.disabled).toBe(true);
    const confirm = page.findAll('button').find(button => button.text() === '确认关联');
    expect(confirm.element.disabled).toBe(true);
    await page.vm.createWmsLink();
    expect(requestApi.mock.calls.some(([request]) => request?.url?.endsWith('/wms-allocations/'))).toBe(false);
    page.unmount();
  });

  it('saves an ETA from the logistics page and allocates a selected WMS row from a confirmed receipt', async () => {
    mocks.requestApi.mockImplementation(async (request) => {
      if (!request?.url) return { success: true, data: [] };
      if (request.url.endsWith('/dispatch-options/')) return { success: true, data: { countries: [], freight_companies: [], warehouses: [] } };
      if (request.url.endsWith('/dispatch-candidates/') || request.url.endsWith('/dispatch-batches/')) return { success: true, data: [], count: 0 };
      if (request.url.endsWith('/dispatch-batches/7/')) return { success: true, data: batch };
      if (request.url.endsWith('/expected-warehouse-date/')) return { success: true, data: { ...batch, expected_warehouse_date: request.data.expected_warehouse_date, version: 5 } };
      if (request.url.endsWith('/inbound-orders/12/')) return { success: true, data: inbound };
      if (request.url.endsWith('/wms-reconciliation/')) return { success: true, data: [{ receipt_line_id: 41, inbound_line_id: 31, sku: 'SKU-1', local_received_quantity: 5, allocated_quantity: 0, remaining_quantity: 5, allocations: [] }] };
      if (request.url.endsWith('/wms-candidates/')) return { success: true, data: [{ id: 99, external_inbound_id: 'WMS-9', external_line_id: '1', received_quantity: 8, remaining_quantity: 8 }] };
      if (request.url.endsWith('/wms-allocations/')) return { success: true, data: { id: 52, version: 1 } };
      return { success: true, data: [] };
    });
    const page = mountPage();
    await flushPromises();
    await page.vm.openBatch(batch);
    page.vm.etaDate = '2026-11-08';
    page.vm.etaReason = '船期调整';
    await page.vm.saveExpectedDate();
    expect(requestApi.mock.calls.find(([request]) => request.url.endsWith('/expected-warehouse-date/'))[0].data)
      .toEqual({ expected_version: 4, expected_warehouse_date: '2026-11-08', reason: '船期调整' });

    await page.vm.openInbound(inbound);
    await page.vm.openWmsCandidates(page.vm.wmsReconciliation[0]);
    page.vm.wmsSelectedId = 99;
    page.vm.wmsQuantity = 3;
    await page.vm.createWmsLink();
    const allocation = requestApi.mock.calls.find(([request]) => request.url.endsWith('/wms-allocations/'))[0];
    expect(allocation.data).toEqual({ inbound_line_id: 31, wms_line_id: 99, quantity: 3, notes: '' });
    expect(allocation.headers['Idempotency-Key']).toBeTruthy();
    page.unmount();
  });
});
