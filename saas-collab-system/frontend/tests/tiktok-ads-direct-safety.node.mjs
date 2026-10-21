import { test } from 'node:test';
import assert from 'node:assert/strict';
import { captureAdsDirectCallback, navigateAdsDirect, prepareAdsDirect, takeAdsManualCallback,
  validateAdsOfficialUrl, ADS_DIRECT_PATH, ADS_DIRECT_CONTEXT_KEY } from '../src/utils/tiktokAdsDirect.js';
import { TK_DIRECT_CONTEXT_KEY } from '../src/utils/tiktokBrowserBridge.js';
const origin = 'https://saas.example.test';
const callback = origin + ADS_DIRECT_PATH;
const official = 'https://business-api.tiktok.com/portal/auth?app_id=demo&state=demo&redirect_uri=' + encodeURIComponent(callback);
const direct = () => ({ browser_token: 'DEMO', callback_url: callback, expires_at: new Date(Date.now() + 60000).toISOString() });
test('Ads accepts documented auth_code/code and optional app id, rejects duplicates and unknowns', () => {
  for (const [search, valid] of [
    ['?auth_code=DEMO&state=demo', true], ['?code=DEMO&state=demo', true],
    ['?auth_code=DEMO&code=DEMO&state=demo', true], ['?error=denied&state=demo', true],
    ['?auth_code=DEMO&code=OTHER&state=demo', true], ['?code=a&code=a&state=b', false],
    ['?auth_code=DEMO&code=OTHER&state=demo&id=123456789', true],
    ['?auth_code=DEMO&state=demo&id=wrong', false], ['?auth_code=DEMO&state=demo&id=1234', false],
    ['?auth_code=DEMO&state=demo&id=123456789&id=123456789', false],
    ['?auth_code=a&state=b&state=b', false], ['?auth_code=a', false],
    ['?auth_code=a&state=b&token=c', false], ['?auth_code=a&error=b&state=c', false],
    ['?code=%zz&state=b', false], ['?code=%00&state=b', false], ['?code=' + 'a'.repeat(4097) + '&state=b', false],
  ]) {
    let cleared = false;
    const location = { pathname: ADS_DIRECT_PATH, search, hash: '' };
    const result = captureAdsDirectCallback(location, { replaceState: () => { cleared = true; location.search = ''; } });
    assert.ok(cleared);
    assert.equal(Boolean(result), valid);
  }
});
test('Ads only permits exact official endpoint and registered redirect_uri', () => {
  assert.equal(validateAdsOfficialUrl(official, callback), official);
  for (const url of [official + '&scope=all', official + '&state=other', official + '#demo',
    official.replace('https:', 'http:'), official.replace('.com/', '.com.attacker.test/'),
    official.replace('/portal/auth', '/portal/auth/'), official.replace('https://', 'https://user@')]) {
    assert.throws(() => validateAdsOfficialUrl(url, callback));
  }
  assert.throws(() => validateAdsOfficialUrl(official, origin + '/wrong'));
});
test('Ads manual context is isolated from Shop and consumed before submission', () => {
  const data = new Map([[TK_DIRECT_CONTEXT_KEY, 'SHOP_UNTOUCHED']]);
  const events = [];
  const browser = { location: { origin, assign: () => events.push('navigate') }, sessionStorage: {
    setItem: (key, value) => { data.set(key, value); events.push('store'); }, getItem: key => data.get(key), removeItem: key => data.delete(key),
  } };
  assert.equal(prepareAdsDirect(direct(), 'a'.repeat(43), official, browser), official);
  assert.deepEqual(events, ['store']);
  for (const value of [origin + '/callback?code=a&state=b', 'https://other.example.test' + ADS_DIRECT_PATH + '?code=a&state=b']) {
    assert.throws(() => takeAdsManualCallback(value, browser));
    assert.ok(data.has(ADS_DIRECT_CONTEXT_KEY));
  }
  const payload = takeAdsManualCallback(callback + '?auth_code=DEMO&code=DEMO&state=demo', browser);
  assert.equal(payload.callback_params.auth_code, 'DEMO');
  assert.equal(data.has(ADS_DIRECT_CONTEXT_KEY), false);
  assert.equal(data.get(TK_DIRECT_CONTEXT_KEY), 'SHOP_UNTOUCHED');
  assert.throws(() => takeAdsManualCallback(callback + '?code=a&state=b', browser));
  navigateAdsDirect(direct(), 'a'.repeat(43), official, browser);
  assert.deepEqual(events, ['store', 'store', 'navigate']);
  events.length = 0;
  browser.sessionStorage.setItem = () => { throw new Error('storage denied'); };
  assert.throws(() => navigateAdsDirect(direct(), 'a'.repeat(43), official, browser));
  assert.deepEqual(events, []);
});
test('Ads import strips callback before taking context exactly once', async () => {
  let stored = JSON.stringify({ ...direct(), verifier: 'a'.repeat(43) });
  let cleared = false;
  globalThis.window = { location: { pathname: ADS_DIRECT_PATH, origin, search: '?auth_code=DEMO&state=demo', hash: '' },
    history: { replaceState: () => { cleared = true; } },
    sessionStorage: { getItem: () => stored, removeItem: () => { stored = null; } } };
  try {
    const module = await import('../src/utils/tiktokAdsDirect.js?capture-test');
    assert.ok(cleared);
    assert.equal(module.takeAdsDirectCallback().callback_params.auth_code, 'DEMO');
    assert.equal(stored, null);
    assert.equal(module.takeAdsDirectCallback(), null);
  } finally { delete globalThis.window; }
});
