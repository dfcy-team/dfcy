import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus, { ElButton, ElCheckbox } from 'element-plus';
import AIExternalApiSettings from '../src/views/integrations/AIExternalApiSettings.vue';

vi.mock('../src/api/internalReadonly', () => ({
  fetchInternalReadonlyClients: vi.fn(async () => ({ success: true, data: { items: [] } })),
  fetchInternalReadonlyCapabilities: vi.fn(async () => ({ success: true, data: {
    ready_resources: [
      { code: 'sales_order_items', fields: ['id', 'sales_order_id'], note: '销售商品行', filters: ['sales_order_id'] },
      { code: 'inventory_inbounds', fields: ['id'], note: '仓储入库单行' },
      { code: 'finance_transactions', fields: ['id'], note: '标准化带符号金额' },
      { code: 'advertising_tiktok_spend', fields: ['id'], note: '仅竞价广告花费' },
    ],
    pending_resources: ['advertising_reconciliation'],
    pending_reasons: { advertising_reconciliation: '待接入广告账户实际扣费账单和财务入账关联' },
  } })),
  createInternalReadonlyClient: vi.fn(), fetchInternalReadonlyAudit: vi.fn(),
  reviewInternalReadonlyClient: vi.fn(), rotateInternalReadonlyCredential: vi.fn(),
  setInternalReadonlyClientStatus: vi.fn(), updateInternalReadonlyClient: vi.fn(),
}));

let wrapper;
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; });

describe('四类只读数据块配置界面', () => {
  it('按所选模块显示新增块，真实能力驱动状态并显示未接入原因', async () => {
    wrapper = mount(AIExternalApiSettings, { attachTo: document.body, global: { plugins: [ElementPlus] } });
    await flushPromises();
    const add = wrapper.findAllComponents(ElButton).find(item => item.text() === '新增调用系统');
    await add.trigger('click');
    await flushPromises();
    for (const module of ['销售管理', '库存管理', '财务中心', '广告']) {
      const checkbox = wrapper.findAllComponents(ElCheckbox).find(item => item.text() === module);
      expect(checkbox, module).toBeTruthy();
      await checkbox.find('input').setValue(true);
    }
    await flushPromises();
    const text = document.body.textContent;
    for (const label of ['销售订单商品明细', '退款退货商品明细', '库存入库明细', '库存发运明细', '平台财务费用明细', 'TikTok 广告日花费']) {
      expect(text).toContain(label);
    }
    expect(text).not.toContain('允许字段');
    const lines = wrapper.findAllComponents(ElCheckbox).find(item => item.text().includes('销售订单商品明细'));
    expect(lines.text()).toContain('已接入');
    const pending = wrapper.findAllComponents(ElCheckbox).find(item => item.text().includes('广告费用对账'));
    expect(pending.text()).toContain('待接入');
    expect(pending.attributes('title')).toContain('实际扣费账单');
    expect(pending.props('disabled')).not.toBe(true);
    expect(text).toContain('无需逐字段配置');
  });
});
