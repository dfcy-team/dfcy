import { describe, expect, it } from 'vitest';

import { formatInfluencerError } from '../src/api/influencers';

describe('达人模块错误提示', () => {
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
});
