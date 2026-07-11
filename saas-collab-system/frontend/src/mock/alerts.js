import { successResponse } from './index';

export const mockBusinessAlerts = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '待处理', value: 16 }, { label: '高优先级', value: 4 }, { label: '处理中', value: 7 }, { label: '今日已关闭', value: 9 }
  ],
  items: [
    {
      alert_id: 'DEMO-ALT-001', alert_type: '库存不足', object_ref: 'DEMO-SKU-001', level: 'high', status: 'open',
      owner: '采购组', triggered_at: '2026-07-11 09:18', silence_until: '2026-07-11 13:18', rule_version: 'demo-alert-v3',
      reason: '库存覆盖天数低于演示安全线', dedupe_key: 'demo-tenant|stockout|DEMO-SKU-001|v3',
      handling_records: [{ actor: 'system', action: 'created', at: '2026-07-11 09:18', note: 'Mock 预警生成' }]
    },
    {
      alert_id: 'DEMO-ALT-002', alert_type: 'RPA连续失败', object_ref: 'DEMO-TASK-GROUP-02', level: 'medium', status: 'in_progress',
      owner: '自动化支持组', triggered_at: '2026-07-11 08:40', silence_until: '2026-07-11 12:40', rule_version: 'demo-alert-v3',
      reason: '演示任务连续失败，已转人工检查', dedupe_key: 'demo-tenant|rpa_failure|DEMO-TASK-GROUP-02|v3',
      handling_records: [{ actor: 'demo-operator', action: 'acknowledged', at: '2026-07-11 08:50', note: '仅演示处理记录，未执行 RPA' }]
    },
    {
      alert_id: 'DEMO-ALT-003', alert_type: '数据长期未更新', object_ref: 'DEMO-SYNC-03', level: 'low', status: 'acknowledged',
      owner: '数据运营组', triggered_at: '2026-07-11 07:25', silence_until: '2026-07-12 07:25', rule_version: 'demo-alert-v3',
      reason: '演示数据源刷新时间超过阈值', dedupe_key: 'demo-tenant|stale_data|DEMO-SYNC-03|v3',
      handling_records: [{ actor: 'demo-operator', action: 'acknowledged', at: '2026-07-11 07:40', note: '等待 Mock 数据刷新' }]
    }
  ]
});
