import { describe, expect, it } from 'vitest';

import { formatInfluencerError } from '../src/api/influencers';

describe('达人模块错误提示', () => {
  it('does not misreport a business conflict as a concurrent update', () => {
    expect(formatInfluencerError({ http_status: 409, code: 'STATE_CONFLICT',
      message: '提交内容校验失败，请检查字段提示。', data: { warehouse: ['仓库国家必须与店铺国家一致。'] }
    })).toBe('仓库国家必须与店铺国家一致。');
  });

  it('does not invent a version conflict when the old server omitted details', () => {
    const result = formatInfluencerError({ http_status: 409, message: '提交内容校验失败，请检查字段提示。', data: null });
    expect(result).toContain('保存发生冲突');
    expect(result).not.toContain('被其他操作更新');
  });
  it('将建联任务负责人冲突显示为明确的送样提示', () => {
    const response = {
      success: false,
      code: 'STATE_CONFLICT',
      message: '需要该建联任务负责人创建送样。',
      http_status: 409,
      data: null
    };

    expect(formatInfluencerError(response, '送样创建失败')).toBe('需要该建联任务负责人创建送样。');
  });

  it('兼容尚未升级后端返回的旧英文负责人提示', () => {
    const response = {
      success: false,
      code: 'VALIDATION_ERROR',
      http_status: 409,
      data: {
        owner: ['Sample owner must be assigned to the outreach task for this source.']
      }
    };

    expect(formatInfluencerError(response)).toBe('需要该建联任务负责人创建送样。');
  });

  it('将仓库匹配错误翻译为中文，并为未知英文错误使用中文兜底', () => {
    expect(formatInfluencerError({
      http_status: 400,
      data: { items: ['Each SKU-bearing sample item requires an explicit warehouse.'] }
    })).toBe('无法自动确定送样仓库，请检查店铺国家后缀及有效仓库设置。');
    expect(formatInfluencerError({ http_status: 400, message: 'Unexpected backend exception.' }, '送样创建失败'))
      .toBe('送样创建失败');
  });
});
