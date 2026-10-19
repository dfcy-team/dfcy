import { describe, expect, it } from 'vitest';
import { tiktokTokenFailure } from '../src/utils/tiktokTokenFailure';

const diagnostic = { platform: 'tiktok', stage: 'exchange_token', category: 'platform_error',
  platform_error_code: '36004004', diagnostic_id: 'a'.repeat(32) };
const response = (changes = {}) => ({ data: { diagnostic: { ...diagnostic, ...changes } }, message: 'FAKE_SECRET' });

describe('TK token failure feedback', () => {
  it('explains an invalid authorization code without exposing raw wire messages', () => {
    const feedback = tiktokTokenFailure(response());
    expect(feedback.message).toContain('36004004');
    expect(feedback.message).toContain('重新发起授权');
    expect(feedback.message).toContain('不要在 dfcy 旧站和 SaaS 重复兑换');
    expect(feedback.message).not.toContain('FAKE_SECRET');
  });
  it.each(['timeout_uncertain', 'network_uncertain'])('preserves uncertainty without suggesting a replay: %s', (category) => {
    const feedback = tiktokTokenFailure(response({ category, platform_error_code: undefined }));
    expect(feedback.message).toContain('结果尚不能确认');
    expect(feedback.message).toContain('系统未自动重试');
    expect(feedback.message).toContain('不要重复提交');
  });
  it.each([{ platform: 'shopee' }, { platform: 'lazada' }, { stage: 'verify_store' },
    { diagnostic_id: 'FAKE_SECRET' }, { platform_error_code: 'UNCLASSIFIED' },
    { platform_error_code: 36004004 }, { category: 'identity_rejected' }])('does not override unrelated diagnostics: %j', (changes) => {
    expect(tiktokTokenFailure(response(changes))).toBeNull();
  });
});
