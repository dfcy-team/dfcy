import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ requestApi: vi.fn(), downloadApiFile: vi.fn(), fetchApiFile: vi.fn(), canManage: true }));
vi.mock('../src/api/request', () => ({ requestApi: mocks.requestApi, downloadApiFile: mocks.downloadApiFile, fetchApiFile: mocks.fetchApiFile }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ authorizationStale: false, hasPermission: () => mocks.canManage }) }));
vi.mock('element-plus', async (original) => ({ ...await original(), ElMessage: { success: vi.fn(), error: vi.fn() } }));

import * as api from '../src/api/supplyChainV2';
import { mount } from '@vue/test-utils';
import FeeCostPanelV2 from '../src/components/supply-chain/FeeCostPanelV2.vue';

const historyRow = { id: 77, recorded_amount: '12.0000', reference_number: 'R-77', attachments: [] };
const context = {
  target: { kind: 'shipment', id: 4, number: 'S-4', version: 5, fee_editable: true },
  fee: null, measurements: [], settlement_supported: true,
  settlement: { version: 1, recorded_amount: '12.0000', status: 'partially_settled' },
  settlement_history: [historyRow]
};
const stubs = {
  'el-alert': true, 'el-descriptions': true, 'el-descriptions-item': true, 'el-form-item': true,
  'el-input': true, 'el-select': true, 'el-option': true, 'el-button': true, 'el-table': true,
  'el-table-column': true, 'el-date-picker': true
};

function mountPanel() {
  return mount(FeeCostPanelV2, { props: { kind: 'shipment', id: 4, version: 5 }, global: { stubs, directives: { loading: () => {} } } });
}

describe('settlement payment vouchers', () => {
  beforeEach(() => {
    mocks.requestApi.mockReset().mockResolvedValue({ success: true, data: context });
    mocks.downloadApiFile.mockReset().mockResolvedValue({ success: true, data: null });
    mocks.canManage = true;
  });

  it('previews an authenticated blob and releases it on unmount', async () => {
    const create=vi.fn(()=> 'blob:receipt'), revoke=vi.fn();
    vi.stubGlobal('URL', { createObjectURL:create,revokeObjectURL:revoke });
    mocks.fetchApiFile.mockResolvedValue({success:true,blob:new Blob(['test'],{type:'image/png'})});
    const wrapper=mountPanel();await wrapper.vm.load();
    await wrapper.vm.previewVoucher(historyRow,{id:3,media_type:'image/png'});
    expect(mocks.fetchApiFile).toHaveBeenCalledWith('/api/internal/supply-chain/v2/costs/shipment/4/settlements/77/vouchers/3/download/');
    expect(create).toHaveBeenCalledTimes(1);wrapper.unmount();expect(revoke).toHaveBeenCalledWith('blob:receipt');vi.unstubAllGlobals();
  });

  it('uses a private revision-bound upload route and authenticated download helper', async () => {
    const file = new File(['%PDF-1.4\n%%EOF'], 'receipt.pdf', { type: 'application/pdf' });
    await api.uploadSettlementVoucher('shipment', 4, 77, file, 'voucher-key');
    expect(mocks.requestApi).toHaveBeenCalledWith(expect.objectContaining({
      method: 'post', url: '/api/internal/supply-chain/v2/costs/shipment/4/settlements/77/vouchers/',
      headers: { 'Idempotency-Key': 'voucher-key' }
    }));
    const request = mocks.requestApi.mock.calls[0][0];
    expect(request.data).toBeInstanceOf(FormData);
    expect(request.data.get('file')).toBe(file);
    await api.downloadSettlementVoucher('batch', 9, 77, 3, 'receipt.pdf');
    expect(mocks.downloadApiFile).toHaveBeenCalledWith(
      '/api/internal/supply-chain/v2/costs/batch/9/settlements/77/vouchers/3/download/', 'receipt.pdf'
    );
  });

  it('attaches successful uploads to their existing history and preserves form state on failure', async () => {
    const wrapper = mountPanel();
    await wrapper.vm.load();
    wrapper.vm.settlement.recorded_amount = '15.0000';
    const row = wrapper.vm.context.settlement_history[0];
    const file = new File(['%PDF-1.4\n%%EOF'], 'receipt.pdf', { type: 'application/pdf' });
    const result = { id: 3, file_name: file.name, media_type: file.type, byte_size: file.size };
    mocks.requestApi.mockResolvedValueOnce({ success: true, data: result });
    await wrapper.vm.uploadVoucher(row, { target: { files: [file], value: 'selected' } });
    expect(row.attachments).toEqual([result]);
    expect(wrapper.vm.settlement.recorded_amount).toBe('15.0000');
    mocks.requestApi.mockResolvedValueOnce({ success: false, message: 'upload failed' });
    await wrapper.vm.uploadVoucher(row, { target: { files: [file], value: 'selected' } });
    expect(row.attachments).toEqual([result]);
    expect(wrapper.vm.settlement.recorded_amount).toBe('15.0000');
  });
});
