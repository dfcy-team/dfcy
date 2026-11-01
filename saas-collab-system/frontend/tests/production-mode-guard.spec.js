import { describe, expect, it } from 'vitest';
import { assertProductionMode } from '../scripts/production-mode-guard.mjs';

describe('生产模式构建关卡', () => {
  it.each([undefined, '', 'true', 'False'])('拒绝未明确关闭模拟模式：%s', (value) => {
    expect(() => assertProductionMode('build', { VITE_USE_MOCK: value })).toThrow('VITE_USE_MOCK=false');
  });
  it('允许正式构建和本地开发', () => {
    expect(() => assertProductionMode('build', { VITE_USE_MOCK: 'false' })).not.toThrow();
    expect(() => assertProductionMode('serve', {})).not.toThrow();
  });
});
