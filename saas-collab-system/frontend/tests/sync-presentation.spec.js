import { describe, expect, it } from 'vitest';
import { syncTime, syncCount, syncError, syncWorkspaceError } from '../src/utils/syncPresentation';
describe('同步事实展示', () => {
  it('distinguishes missing counts from measured zero', () => {
    expect(syncCount(null)).toBe('—'); expect(syncCount(undefined)).toBe('—'); expect(syncCount(0)).toBe('0');
  });
  it('renders time consistently in UTC', () => {
    expect(syncTime('2026-09-14T08:00:00+08:00')).toBe('2026-09-14 00:00:00'); expect(syncTime(null)).toBe('—');
  });
  it('does not show internal exception strings', () => {
    expect(syncError("[ErrorDetail(string='Approved live configuration is missing')]", 'CONFIG')).toContain('只读准入');
    expect(syncError('ErrorDetail(string=unknown)', 'FAILED')).not.toContain('ErrorDetail');
  });
  it('explains transport failures without inferring a task state change', () => {
    expect(syncWorkspaceError('timeout of 10000ms exceeded')).toContain('不代表任务状态已变化');
    expect(syncWorkspaceError('Network Error')).toContain('恢复连接后重试');
  });
});
