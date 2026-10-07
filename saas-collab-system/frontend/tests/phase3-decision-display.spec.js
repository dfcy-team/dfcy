import { describe, expect, it } from 'vitest';
import { decisionStatusLabel, decisionTableEmptyText } from '../src/components/phase3DecisionDisplay';

describe('经营决策列表呈现', () => {
  it('translates known lifecycle and business alert states while preserving unknown source values', () => {
    expect(['suggested', 'confirmed', 'rejected', 'open', 'assigned', 'silenced', 'closed'].map(decisionStatusLabel))
      .toEqual(['待复核', '已确认', '已拒绝', '待处理', '已分派', '已静默', '已关闭']);
    expect(decisionStatusLabel('external-state')).toBe('external-state');
  });

  it('keeps read errors separate from genuine no-records descriptions', () => {
    const noReviews = '当前筛选条件下没有复盘记录；可能尚未生成或已处理完毕，这不代表没有库存或经营风险。';
    expect(decisionTableEmptyText('', noReviews)).toBe(noReviews);
    expect(decisionTableEmptyText('接口读取失败', noReviews)).toBe('数据读取失败，请查看上方错误信息。');
  });
});
