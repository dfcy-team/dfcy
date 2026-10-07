import { describe, expect, it } from 'vitest';
import { feishuRuleConfig, feishuRequestId } from '../src/utils/feishuRule';

describe('飞书规则保存与真实投递标识', () => {
  it('通知只提交当前类型字段，不携带报表排程默认值', () => {
    const config = feishuRuleConfig('notification', { scene: 'business_alert', message: '测试', format: 'text', recipient_user_ids: [1], hour: '09:00', schedule: 'daily', report_type: 'comprehensive' });
    expect(config).toEqual({ scene: 'business_alert', message: '测试', format: 'text', recipient_user_ids: [1] });
  });
  it('报表小时转换为整数并保留允许的日期筛选', () => {
    expect(feishuRuleConfig('report', { report_type: 'sales', recipient_user_ids: [1], hour: '09:00', schedule: 'weekly', format: 'file' }, { filters: { date_from: '2026-09-01', date_to: '2026-09-07' }, obsolete: 'ignored' })).toEqual({ report_type: 'sales', recipient_user_ids: [1], schedule: 'weekly', hour: 9, format: 'file', filters: { date_from: '2026-09-01', date_to: '2026-09-07' } });
  });
  it('旧价格审批规则转为本系统枚举，不向飞书原生审批传递Approval Code', () => {
    expect(feishuRuleConfig('approval', { approval_type: 'pricing', recipient_user_ids: [1], format: 'card' }, { approval_code: 'obsolete' })).toEqual({ approval_type: 'price', recipient_user_ids: [1] });
  });
  it('拒绝非JSON对象的高级配置', () => {
    for (const input of [null, [], 'x']) expect(() => feishuRuleConfig('report', {}, input)).toThrow('JSON对象');
  });
  it('真实消息请求使用合法且不同的UUID', () => {
    const first = feishuRequestId(); const second = feishuRequestId();
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(second).not.toBe(first);
  });
});
