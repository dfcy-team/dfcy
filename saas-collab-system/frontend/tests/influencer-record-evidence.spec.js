import { describe, expect, it } from 'vitest';
import { archiveStateLabel, hasPlatformIdentity, matchedVideoCount, publishedEvidenceNotice, taskProgressNotice } from '../src/views/influencers/recordEvidence';
import { formatTaskDateTime } from '../src/views/influencers/taskDateTime';

describe('read-only identity and historical evidence presentation', () => {
  it('does not invent a platform identity from a draft name or code', () => {
    const draft = Object.freeze({ name: 'Historical name', code: 'draft-123', status: 'active', nickname_id: '', profile: null });
    expect(hasPlatformIdentity(draft)).toBe(false);
    expect(archiveStateLabel(draft)).toBe('启用 · 身份待补全');
    expect(draft.status).toBe('active');
  });
  it.each([{ nickname_id: 'creator' }, { profile: { external_influencer_id: '0001234567890123456789' } }])('accepts either recorded identity without requiring both', (identity) => {
    expect(hasPlatformIdentity(identity)).toBe(true);
    expect(archiveStateLabel({ ...identity, status: 'active' })).toBe('正常');
  });
  it('preserves inactive and blacklist precedence', () => {
    expect(archiveStateLabel({ status: 'inactive' })).toBe('停用');
    expect(archiveStateLabel({ status: 'active', is_blacklisted: true })).toBe('已拉黑');
    expect(hasPlatformIdentity({ nickname_id: '  ', profile: { external_influencer_id: ' ' } })).toBe(false);
  });
  it('explains an imported pending task at target without changing state', () => {
    const task = Object.freeze({ source: 'feishu_full_20260908', status: 'pending', target_count: 20, sample_fulfillment_influencer_count: 21 });
    expect(taskProgressNotice(task)).toContain('保留来源登记的状态');
    expect(taskProgressNotice(task)).toContain('已达到送样目标');
    expect(task.status).toBe('pending');
  });
  it('does not claim manual tasks were imported, or treat duplicate samples as unique creators', () => {
    const task = { source: 'manual', status: 'pending', target_count: 20, sample_fulfillment_count: 25, sample_fulfillment_influencer_count: 2 };
    expect(taskProgressNotice(task)).toContain('仍为待开始');
    expect(taskProgressNotice(task)).not.toContain('历史导入');
    expect(taskProgressNotice(task)).not.toContain('已达到');
    expect(taskProgressNotice({ ...task, status: 'completed' })).toBe('');
    expect(taskProgressNotice({ status: 'pending', target_count: 20 })).toBe('');
  });
  it('distinguishes unknown video counts from confirmed missing evidence', () => {
    expect(matchedVideoCount({})).toBeNull();
    expect(publishedEvidenceNotice({ status: 'published' })).toBe('');
    expect(matchedVideoCount({ video_matches: [] })).toBe(0);
    expect(matchedVideoCount({ video_match_count: '2' })).toBe(2);
  });
  it('explains an imported published status without claiming a video was found or not published', () => {
    const sample = Object.freeze({ status: 'published', source: 'feishu_full_20260908', video_match_count: 0 });
    expect(publishedEvidenceNotice(sample)).toContain('飞书历史导入');
    expect(publishedEvidenceNotice(sample)).toContain('不能以此判定未发布');
    expect(sample.status).toBe('published');
    expect(publishedEvidenceNotice({ ...sample, video_match_count: 1 })).toBe('');
    expect(publishedEvidenceNotice({ ...sample, status: 'shipped' })).toBe('');
  });
  it('renders UTC cross-midnight values in Shanghai time without filling absent timestamps', () => {
    expect(formatTaskDateTime('2026-09-23T16:00:00Z')).toBe('2026-09-24 00:00:00');
    expect(formatTaskDateTime('2026-09-24T00:00:00+08:00')).toBe('2026-09-24 00:00:00');
    expect(formatTaskDateTime(null)).toBe('—');
  });
});
