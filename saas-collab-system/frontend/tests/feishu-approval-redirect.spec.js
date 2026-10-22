import { describe, expect, it } from 'vitest';
import { rememberApprovalReturn, takeApprovalReturn } from '../src/utils/feishuApprovalRedirect';

const memory = () => { const map = new Map(); return { getItem: (key) => map.get(key), setItem: (key, value) => map.set(key, value), removeItem: (key) => map.delete(key) }; };
describe('飞书通知审批深链接登录后返回', () => {
  it('仅保存单个审批详情且回调后一次性消费', () => {
    const storage = memory(); rememberApprovalReturn('/workflow/approvals/42', storage, 1000);
    expect(takeApprovalReturn(storage, 2000)).toBe('/workflow/approvals/42');
    expect(takeApprovalReturn(storage, 2000)).toBeUndefined();
  });
  it('保留V249分析报表的指定数据集与日期范围', () => {
    const path = '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16';
    const storage = memory(); rememberApprovalReturn(path, storage, 1000);
    expect(takeApprovalReturn(storage, 2000)).toBe(path);
  });
  it.each(['sales', 'advertising'])('保留%s图表详情的全部受支持筛选条件', (dataset) => {
    const path = `/reports/basic?tab=analysis&feishu_dataset=${dataset}&date_from=2026-10-16&date_to=2026-10-17&store_id=1234567890123456789&region=GB&currency=GBP`;
    const storage = memory(); rememberApprovalReturn(path, storage, 1000);
    expect(takeApprovalReturn(storage, 2000)).toBe(path);
  });
  it.each(['orders', 'returns'])('保留%s业务提醒的筛选条件，并在五分钟内一次性消费', (source) => {
    const path = `/sales-management/${source}?reminder_id=1&reminder_membership=0&date_from=2026-10-16&date_to=2026-10-17&platforms=amazon%2Cshopify&store_ids=12%2C13&order_status=shipped&sku_exact=true`;
    const storage = memory(); rememberApprovalReturn(path, storage, 1000);
    expect(takeApprovalReturn(storage, 300000)).toBe(path);
    expect(takeApprovalReturn(storage, 300000)).toBeUndefined();

    rememberApprovalReturn(path, storage, 1000);
    expect(takeApprovalReturn(storage, 301000)).toBeUndefined();
  });
  it('仅接受提醒订单与退货路径、有效编号及已知筛选字段', () => {
    for (const path of [
      '/sales-management/orders?reminder_id=1&reminder_membership=0&unknown=x',
      '/sales-management/orders?reminder_id=1&reminder_membership=0&status=ok&status=shipped',
      '/sales-management/orders?reminder_id=1&reminder_id=2&reminder_membership=0',
      '/sales-management/orders?reminder_id=0&reminder_membership=0',
      '/sales-management/orders?reminder_id=-1&reminder_membership=0',
      '/sales-management/orders?reminder_id=1.2&reminder_membership=0',
      '/sales-management/orders?reminder_id=1&reminder_membership=-1',
      '/sales-management/orders?reminder_id=1&reminder_membership=01',
      '/sales-management/orders?reminder_id=1&reminder_membership=0&reminder_membership=2',
      '/sales-management/orders?reminder_id=1&reminder_membership=0&sku=%5Cevil',
      '/sales-management/orders?reminder_id=1&reminder_membership=0&sku=%0Aevil',
      '/sales-management/orders?reminder_id=1&reminder_membership=0#hash',
      '/sales-management/orders/1?reminder_id=1&reminder_membership=0',
      '/sales-management/refunds?reminder_id=1&reminder_membership=0',
      'https://evil.example/sales-management/orders?reminder_id=1&reminder_membership=0'
    ]) {
      const storage = memory(); rememberApprovalReturn(path, storage, 1000);
      expect(takeApprovalReturn(storage, 2000)).toBeUndefined();
    }
  });
  it('接受500字符百分号编码筛选值和正membership，拒绝501字符', () => {
    const filter = '中'.repeat(500);
    const path = `/sales-management/orders?reminder_id=12&reminder_membership=345&sku=${encodeURIComponent(filter)}`;
    const storage = memory(); rememberApprovalReturn(path, storage, 1000);
    expect(takeApprovalReturn(storage, 2000)).toBe(path);

    const tooLong = `/sales-management/orders?reminder_id=12&reminder_membership=345&sku=${encodeURIComponent(`${filter}中`)}`;
    rememberApprovalReturn(tooLong, storage, 1000);
    expect(takeApprovalReturn(storage, 2000)).toBeUndefined();
  });
  it('仅接受白名单报表数据集及可选的合法单侧日期', () => {
    for (const dataset of ['sales', 'sales_skus', 'inventory', 'inventory_value', 'refunds', 'finance']) {
      for (const suffix of ['', '&date_from=2026-10-16', '&date_to=2026-10-16', '&date_from=2026-10-16&date_to=2026-10-17']) {
        const path = `/reports/basic?tab=analysis&feishu_dataset=${dataset}${suffix}`;
        const storage = memory(); rememberApprovalReturn(path, storage, 1000);
        expect(takeApprovalReturn(storage, 2000)).toBe(path);
      }
    }
    const storage = memory(); rememberApprovalReturn('/reports/basic', storage, 1000);
    expect(takeApprovalReturn(storage, 2000)).toBe('/reports/basic');
  });
  it('拒绝外部链接、带参数路径和超时目标', () => {
    for (const path of [
      'https://evil.example', '//evil.example', '/workflow/approvals/42?to=https://evil.example', '/login', '/workflow/approvals/0',
      '/reports/basic?tab=analysis&feishu_dataset=unknown&date_from=2026-10-16&date_to=2026-10-16',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-02-30&date_to=2026-10-16',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-02-30',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_to=not-a-date',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-17&date_to=2026-10-16',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16&x=1',
      '/reports/basic?tab=analysis&tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16#hash',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16\\evil',
      '/reports/basic?tab=analysis&feishu_dataset=advertising&store_id=0123',
      '/reports/basic?tab=analysis&feishu_dataset=sales&store_id=12345678901234567890',
      '/reports/basic?tab=analysis&feishu_dataset=sales&region=gb',
      '/reports/basic?tab=analysis&feishu_dataset=sales&region=GB<script>',
      '/reports/basic?tab=analysis&feishu_dataset=sales&currency=US',
      '/reports/basic?tab=analysis&feishu_dataset=sales&currency=US%0A',
      '/reports/basic?tab=analysis&feishu_dataset=sales&store_id=123&store_id=456',
      '/reports/basic?tab=analysis&feishu_dataset=sales&region=GB&region=US',
      '/reports/basic?tab=analysis&feishu_dataset=sales&currency=GBP&currency=USD',
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16&store_id=1&region=GB&currency=GBP&extra=x'
    ]) {
      const storage = memory(); rememberApprovalReturn(path, storage, 1000); expect(takeApprovalReturn(storage, 2000)).toBeUndefined();
    }
    const storage = memory(); rememberApprovalReturn('/workflow/approvals/42', storage, 1000);
    expect(takeApprovalReturn(storage, 301001)).toBeUndefined();
  });
  it('浏览器不允许存储时不影响原登录逻辑', () => {
    const storage = { removeItem() { throw new Error('disabled'); }, getItem() { throw new Error('disabled'); } };
    expect(() => rememberApprovalReturn('/workflow/approvals/42', storage)).not.toThrow();
    expect(takeApprovalReturn(storage)).toBeUndefined();
  });
});
