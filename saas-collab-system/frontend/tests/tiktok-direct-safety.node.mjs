import { test } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { captureTikTokDirectCallback, captureTikTokReceipt, createTikTokBrowserVerifier, navigateTikTokDirect,
  validateTikTokOfficialUrl, prepareTikTokDirect, takeTikTokManualCallback, TK_DIRECT_PATH, TK_RESULT_PATH, TK_DIRECT_CONTEXT_KEY } from '../src/utils/tiktokBrowserBridge.js';

const official = 'https://services.tiktokshop.com/open/authorize?service_id=demo&state=demo';
const origin = 'https://saas.example.test';
const direct = () => ({ browser_token: 'DEMO', callback_url: origin + TK_DIRECT_PATH, expires_at: new Date(Date.now() + 60000).toISOString() });
test('verifier is 32 cryptographic bytes encoded as 43 URL-safe characters', () => {
  const values = Array.from({ length: 40 }, () => createTikTokBrowserVerifier(webcrypto));
  assert.equal(new Set(values).size, 40);
  assert.ok(values.every((value) => /^[A-Za-z0-9_-]{43}$/.test(value)));
});
test('official URL rejects extra parameters, credentials, fragments and deceptive hosts', () => {
  assert.equal(validateTikTokOfficialUrl(official), official);
  assert.ok(validateTikTokOfficialUrl(official.replace('services.', 'services.us.')));
  for (const value of [official + '&code=demo', official + '&state=other',
    official.replace('https:', 'http:'), official.replace('.com/', '.com.attacker.test/'),
    official.replace('/open/authorize', '/open/authorize/'), official.replace('https://', 'https://user@')]) {
    assert.throws(() => validateTikTokOfficialUrl(value));
  }
  assert.throws(() => validateTikTokOfficialUrl(official + '#demo'));
});
test('manual Shop callback requires own registered URL, prepares without navigation, consumes once', () => {
  let stored;
  const browser = { location: { origin, assign: () => assert.fail('manual must not navigate') }, sessionStorage: {
    setItem: (_, value) => { stored = value; }, getItem: () => stored, removeItem: () => { stored = null; },
  } };
  assert.equal(prepareTikTokDirect(direct(), 'a'.repeat(43), official, browser), official);
  for (const url of ['https://other.example.test' + TK_DIRECT_PATH, origin + '/callback', origin + TK_DIRECT_PATH + '/']) {
    assert.throws(() => takeTikTokManualCallback(url + '?code=DEMO&state=demo', browser));
    assert.ok(stored);
  }
  const payload = takeTikTokManualCallback(origin + TK_DIRECT_PATH + '?code=DEMO&state=demo', browser);
  assert.equal(payload.callback_params.code, 'DEMO');
  assert.equal(stored, null);
  assert.throws(() => takeTikTokManualCallback(origin + TK_DIRECT_PATH + '?code=DEMO&state=demo', browser));
});
test('context is persisted before same-tab navigation; storage failure never navigates', () => {
  const events = [];
  let stored;
  const browser = { location: { origin, assign: () => events.push('navigate') }, sessionStorage: {
    setItem: (key, value) => { assert.equal(key, TK_DIRECT_CONTEXT_KEY); stored = value; events.push('store'); },
    getItem: () => stored,
  } };
  navigateTikTokDirect(direct(), 'a'.repeat(43), official, browser);
  assert.deepEqual(events, ['store', 'navigate']);
  assert.deepEqual(Object.keys(JSON.parse(stored)).sort(), ['browser_token', 'callback_url', 'expires_at', 'verifier']);
  events.length = 0;
  browser.sessionStorage.setItem = () => { throw new Error('blocked'); };
  assert.throws(() => navigateTikTokDirect(direct(), 'a'.repeat(43), official, browser));
  assert.deepEqual(events, []);
});
test('callback destination must match exact same-origin HTTPS path without decorations', () => {
  for (const callback_url of [origin + TK_DIRECT_PATH + '?x=1', origin + TK_DIRECT_PATH + '#x',
    origin + TK_DIRECT_PATH + '/', 'https://other.example.test' + TK_DIRECT_PATH, origin.replace('https', 'http') + TK_DIRECT_PATH,
    'https://user@saas.example.test' + TK_DIRECT_PATH]) {
    assert.throws(() => navigateTikTokDirect({ ...direct(), callback_url }, 'a'.repeat(43), official,
      { location: { origin, assign: () => assert.fail('must not navigate') } }));
  }
});
test('callback strips URL before validation, rejects duplicates, unknown fields, oversize values', () => {
  for (const search of ['?code=demo&state=demo', '?code=a&code=b&state=c', '?code=a&state=c&token=demo',
    '?code=a&state=', '?error=denied&state=demo', '?code=a&error=x&state=b', '?code=' + 'a'.repeat(4097) + '&state=b',
    '?code=%00&state=b', '?code=%zz&state=b']) {
    const location = { pathname: TK_DIRECT_PATH, search, hash: '' };
    let cleared = false;
    const result = captureTikTokDirectCallback(location, { replaceState: () => { cleared = true; location.search = ''; } });
    assert.ok(cleared);
    assert.equal(Boolean(result), ['?code=demo&state=demo', '?error=denied&state=demo'].includes(search));
  }
});
test('safe binding resume survives legacy capture but receipt mixed with query never does', () => {
  const query = '?binding_id=12345678-1234-1234-1234-123456789abc';
  assert.equal(captureTikTokReceipt({ pathname: TK_RESULT_PATH, search: query, hash: '' },
    { replaceState: () => assert.fail('safe resume must survive') }), '');
  let cleared = false;
  assert.equal(captureTikTokReceipt({ pathname: TK_RESULT_PATH, search: query, hash: '#receipt=a.b' },
    { replaceState: () => { cleared = true; } }), '');
  assert.ok(cleared);
});
test('import-time capture precedes requests and takes context exactly once without storing codes', async () => {
  let stored = JSON.stringify({ ...direct(), verifier: 'a'.repeat(43) });
  const events = [];
  globalThis.window = { location: { pathname: TK_DIRECT_PATH, origin, search: '?code=DEMO_CODE&state=demo', hash: '' },
    history: { replaceState: () => events.push('strip') },
    sessionStorage: { getItem: () => stored, removeItem: () => { stored = null; events.push('clear'); } } };
  try {
    const module = await import('../src/utils/tiktokBrowserBridge.js?capture-test');
    assert.deepEqual(events, ['strip']);
    const payload = module.takeTikTokDirectCallback();
    assert.equal(payload.callback_params.code, 'DEMO_CODE');
    assert.equal(stored, null);
    assert.equal(module.takeTikTokDirectCallback(), null);
  } finally { delete globalThis.window; }
});

test('manual no-state callback retains tab proof for backend known-shop validation only', () => {
  const data = new Map();
  const browser = { location: { origin }, sessionStorage: {
    setItem: (key, value) => data.set(key, value), getItem: key => data.get(key), removeItem: key => data.delete(key),
  } };
  prepareTikTokDirect(direct(), 'a'.repeat(43), official, browser);
  const url = origin + TK_DIRECT_PATH + '?code=DEMO&app_key=DEMO_APP&shop_region=PH';
  const payload = takeTikTokManualCallback(url, browser);
  assert.equal(payload.callback_params.code, 'DEMO');
  assert.equal(payload.callback_params.state, undefined);
  assert.equal(payload.browser_verifier, 'a'.repeat(43));
  assert.equal(data.size, 0);
  assert.throws(() => takeTikTokManualCallback(url, browser));
});

test('automatic no-state callback is captured once without persisting its code', async () => {
  let stored = JSON.stringify({ ...direct(), verifier: 'a'.repeat(43) });
  let stripped = false;
  globalThis.window = { location: { pathname: TK_DIRECT_PATH, origin,
    search: '?code=DEMO&app_key=DEMO_APP&shop_region=PH', hash: '' },
    history: { replaceState: () => { stripped = true; } },
    sessionStorage: { getItem: () => stored, removeItem: () => { stored = null; } } };
  try {
    const module = await import('../src/utils/tiktokBrowserBridge.js?known-shop-no-state');
    assert.equal(stripped, true);
    const payload = module.takeTikTokDirectCallback();
    assert.equal(payload.callback_params.code, 'DEMO');
    assert.equal(payload.callback_params.state, undefined);
    assert.equal(stored, null);
    assert.equal(module.takeTikTokDirectCallback(), null);
  } finally { delete globalThis.window; }
});
