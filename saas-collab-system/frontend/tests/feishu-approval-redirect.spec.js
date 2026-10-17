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
      '/reports/basic?tab=analysis&feishu_dataset=sales&date_from=2026-10-16&date_to=2026-10-16\\evil'
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
