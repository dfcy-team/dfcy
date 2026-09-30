import { describe, expect, it } from 'vitest';
import { FEISHU_AUTHORIZE_URL, validateAuthorizeUrl, validFeishuMessage } from '../src/utils/feishuQrLogin';

describe('Feishu QR login message validation', () => {
  it('accepts only passport messages with both SDK match flags and a bounded code', () => {
    const source = {};
    const sdk = { matchOrigin: (origin) => origin === 'https://passport.feishu.cn', matchData: (data) => data?.tmp_code === 'abc' };
    expect(validFeishuMessage({ origin: 'https://passport.feishu.cn', source, data: { tmp_code: 'abc' } }, source, sdk)).toBe('abc');
    expect(validFeishuMessage({ origin: 'https://evil.example', source, data: { tmp_code: 'abc' } }, source, sdk)).toBeNull();
    expect(validFeishuMessage({ origin: 'https://passport.feishu.cn', source, data: { tmp_code: 'nope' } }, source, sdk)).toBeNull();
    expect(validFeishuMessage({ origin: 'https://passport.feishu.cn', source, data: { tmp_code: 'x'.repeat(2049) } }, source, { ...sdk, matchData: () => true })).toBeNull();
    expect(validFeishuMessage({ origin: 'https://passport.feishu.cn', source: {}, data: { tmp_code: 'abc' } }, source, sdk)).toBeNull();
  });

  it('pins authorization navigation to the official endpoint', () => {
    expect(FEISHU_AUTHORIZE_URL).toBe('https://passport.feishu.cn/suite/passport/oauth/authorize');
    const valid = validateAuthorizeUrl(`${FEISHU_AUTHORIZE_URL}?client_id=x&state=s&redirect_uri=https%3A%2F%2Fapp.example%2Fcb&response_type=code`);
    expect(valid?.origin).toBe('https://passport.feishu.cn');
    expect(validateAuthorizeUrl('https://evil.example/suite/passport/oauth/authorize?client_id=x&state=s&redirect_uri=https://a.test&response_type=code')).toBeNull();
    expect(validateAuthorizeUrl(`${FEISHU_AUTHORIZE_URL}?client_id=x&state=s&redirect_uri=https://a.test&response_type=token`)).toBeNull();
  });
});
