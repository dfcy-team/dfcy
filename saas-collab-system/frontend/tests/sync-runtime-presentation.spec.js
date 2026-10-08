import { describe, expect, it } from 'vitest';
import { syncRuntimePresentation } from '../src/utils/syncPresentation';

describe('sync runtime presentation', () => {
  it('shows DB runtime state and separates this queue start, current wait and progress', () => {
    const text = syncRuntimePresentation({
      state: 'queued', queued_since: '2026-10-04T01:00:00Z', wait_seconds: 42,
      last_progress_at: '2026-10-04T01:02:00Z', delivery_state: 'absent'
    });
    expect(text).toContain('排队中');
    expect(text).toContain('本次排队起点');
    expect(text).toContain('当前等待 42 秒');
    expect(text).toContain('最近进度');
    expect(text).toContain('最近检查时队列未发现');
  });

  it('keeps old API responses readable and masks credential-like notice values', () => {
    expect(syncRuntimePresentation()).toBe('运行状态未知 · 队列状态未知');
    expect(syncRuntimePresentation({ state: 'credential_wait', notice: 'token: abc123' })).toContain('token=[已隐藏]');
    expect(syncRuntimePresentation({ state: 'unknown', notice: 'x'.repeat(300) }).length).toBeLessThan(250);
    expect(syncRuntimePresentation({ state: 'success' })).toContain('成功');
    expect(syncRuntimePresentation({ state: 'cancelled' })).toContain('已取消');
  });
});
