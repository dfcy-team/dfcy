import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { adsResumeSessionId, captureAdsReceipt, navigateAdsBridge, ADS_RESULT_PATH } from '../src/utils/tiktokAdsBridge';
const session = '11111111-2222-4333-8444-555555555555';
const receipt = 'a'.repeat(64);
describe('independent Ads OAuth bridge', () => {
  it('clears fragment before handing off only opaque identifiers', () => {
    const history = { state: {}, replaceState: vi.fn() };
    expect(captureAdsReceipt({ pathname: ADS_RESULT_PATH, search: '', hash: `#session_id=${session}&receipt_id=${receipt}` }, history))
      .toEqual({ session_id: session, receipt_id: receipt });
    expect(history.replaceState).toHaveBeenNthCalledWith(1, history.state, '', ADS_RESULT_PATH);
    expect(history.replaceState).toHaveBeenLastCalledWith(history.state, '', `${ADS_RESULT_PATH}?session_id=${session}`);
    expect(history.replaceState.mock.calls.every(call => !call[2].includes(receipt))).toBe(true);
  });
  it.each([
    `#session_id=${session}&receipt_id=${receipt}&auth_code=bad`,
    `#session_id=${session}&receipt_id=${receipt}&receipt_id=${receipt}`, '#auth_code=bad', '#session_id=x&receipt_id=y',
  ])('rejects malformed return %s', (hash) => {
    const history = { replaceState: vi.fn() };
    expect(captureAdsReceipt({ pathname: ADS_RESULT_PATH, search: '', hash }, history)).toBeNull();
    expect(history.replaceState).toHaveBeenCalledOnce();
  });
  it('rejects query material and leaves Shop routes alone', () => {
    const history = { replaceState: vi.fn() };
    expect(captureAdsReceipt({ pathname: ADS_RESULT_PATH, search: '?code=bad', hash: `#session_id=${session}&receipt_id=${receipt}` }, history)).toBeNull();
    history.replaceState.mockClear();
    expect(captureAdsReceipt({ pathname: '/integrations/tiktok/authorization-result' }, history)).toBeNull();
    expect(history.replaceState).not.toHaveBeenCalled();
  });
  it('uses the same tab and only the fixed Ads relay', () => {
    const navigate = vi.fn();
    navigateAdsBridge('https://dingfengchuangyu.com/saas-tk-ads/start#ticket=fake.signature', navigate);
    expect(navigate).toHaveBeenCalledOnce();
    expect(() => navigateAdsBridge('https://evil.test/saas-tk-ads/start#ticket=fake.signature', navigate)).toThrow();
    expect(() => navigateAdsBridge('https://dingfengchuangyu.com/saas-tk/start#ticket=fake.signature', navigate)).toThrow();
  });
  it('preserves only a valid session query on reload, with no callback receipt', () => {
    const history = { state: {}, replaceState: vi.fn() };
    const search = `?session_id=${session}`;
    expect(captureAdsReceipt({ pathname: ADS_RESULT_PATH, search, hash: '' }, history)).toBeNull();
    expect(history.replaceState).toHaveBeenCalledExactlyOnceWith(history.state, '', ADS_RESULT_PATH + search);
    expect(adsResumeSessionId(search)).toBe(session);
  });
  it.each(['?session_id=bad', `?session_id=${session}&receipt_id=${receipt}`, `?session_id=${session}&session_id=${session}`])('rejects unsafe resume query %s', search => {
    const history = { replaceState: vi.fn() };
    expect(adsResumeSessionId(search)).toBe('');
    captureAdsReceipt({ pathname: ADS_RESULT_PATH, search, hash: '' }, history);
    expect(history.replaceState).toHaveBeenCalledExactlyOnceWith(undefined, '', ADS_RESULT_PATH);
  });
  it('registers isolated result route, disables one-use replay and never creates sync jobs in Ads UI', () => {
    const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
    expect(read('../src/router/index.js')).toContain("path: '/integrations/tiktok-ads/authorization-result'");
    expect(read('../src/api/request.js')).toContain('tiktok-ads\\/oauth\\/complete');
    expect(read('../src/components/TikTokAdsSessionPanel.vue')).not.toMatch(/createSyncJob|localStorage|access_token/);
    expect(read('../src/main.js')).toContain("import './utils/tiktokAdsBridge'");
  });
});
