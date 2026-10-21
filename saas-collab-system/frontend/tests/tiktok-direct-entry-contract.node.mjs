import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const read = path => readFileSync(new URL('../src/' + path, import.meta.url), 'utf8');
test('TK entrypoints and result pages do not exchange or navigate legacy relay contracts', () => {
  const dialog = read('components/SubjectApiAccessDialog.vue');
  assert.doesNotMatch(dialog, /navigateTikTokBridge|navigateAdsBridge|browser_bridge_url|tiktok_pending_token/);
  assert.match(dialog, /if \(!response\.data\?\.direct_callback\) throw/);
  assert.match(dialog, /填写\/粘贴回调 URL/);
  assert.doesNotMatch(read('views/integrations/TikTokAuthorizationResult.vue'), /completeTikTokBrowserAuthorization/);
  assert.doesNotMatch(read('views/integrations/TikTokAdsAuthorizationResult.vue'), /completeAdsOAuth/);
});
test('one-use direct POST endpoints explicitly suppress mock fallback and auth replay', () => {
  for (const [path, pattern] of [['api/integrations.js', /export const completeTikTokDirectAuthorization[\s\S]*?\n\}\);/],
    ['api/tiktokAds.js', /export const completeAdsDirectOAuth[\s\S]*?\}\);/]]) {
    const source = read(path).match(pattern)?.[0];
    assert.ok(source);
    assert.match(source, /timeout: 60000/);
    assert.match(source, /noMockFallback: true/);
    assert.match(source, /_authRetried: true/);
  }
});
test('modified Vue script blocks parse as modules without installing dependencies', () => {
  for (const path of ['components/SubjectApiAccessDialog.vue', 'views/integrations/TikTokAuthorizationResult.vue',
    'views/integrations/TikTokAdsAuthorizationResult.vue']) {
    const source = read(path).match(/<script setup>([\s\S]*?)<\/script>/)?.[1];
    assert.ok(source);
    const check = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: source, encoding: 'utf8' });
    assert.equal(check.status, 0, `${path}: ${check.stderr}`);
  }
});
