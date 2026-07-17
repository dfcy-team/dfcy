import { successResponse } from './index';

export const mockFinanceAnalyticsOverview = () => successResponse({
  status: 'mock', api_status: 'mock',
  quality: { status: 'good', score: 97, metric_version: 'demo-finance-v3.0', refreshed_at: '2026-07-11 09:10' },
  metrics: [
    { code: 'BI_FINANCE_STATEMENT', label: '平台账单汇总', value: '***,320', unit: '元', change: '聚合脱敏展示', change_direction: 'up' },
    { code: 'BI_FINANCE_RECEIPT', label: '银行到账汇总', value: '***,860', unit: '元', change: '账号尾号 **** 4821', change_direction: 'up' },
    { code: 'BI_FINANCE_DIFF', label: '对账差异', value: '12,460', unit: '元', change: '8 笔待核查', change_direction: 'down' },
    { code: 'BI_FINANCE_PROFIT', label: '利润分析', value: 'N/A', unit: '', change: '阶段3占位，数据完整后启用', change_direction: '' }
  ],
  trend: [
    { label: '02月', value: 62 }, { label: '03月', value: 68 }, { label: '04月', value: 71 },
    { label: '05月', value: 73 }, { label: '06月', value: 78 }, { label: '07月', value: 81 }
  ],
  count: 3,
  next: null,
  previous: null,
  results: [
    { period_start: '2026-07-01', period_end: '2026-07-31', platform: 'demo', currency: 'CNY', statement_amount: '***,320', receipt_amount: '***,860', difference_amount: '12,460', exception_count: 8, account_mask: '**** 4821', quality_status: 'good' },
    { period_start: '2026-06-01', period_end: '2026-06-30', platform: 'demo', currency: 'USD', statement_amount: '***,180', receipt_amount: '***,120', difference_amount: '2,060', exception_count: 3, account_mask: '**** 1937', quality_status: 'good' },
    { period_start: '2026-05-01', period_end: '2026-05-31', platform: 'demo', currency: 'EUR', statement_amount: '***,740', receipt_amount: '***,510', difference_amount: null, exception_count: 0, account_mask: '**** 7054', quality_status: 'warning' }
  ],
  read_only: true,
  fund_action_available: false
});
