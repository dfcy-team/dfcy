const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const candidate = fs.readFileSync('sync-evidence-hotfix/SyncExecutionRecords-CQKzcVFv.js');
const freshName = 'SyncExecutionRecords-evidence-' + crypto.createHash('sha256').update(candidate).digest('hex').slice(0, 12) + '.js';
const importMap = '<script type="importmap">' + JSON.stringify({ imports: { '/assets/SyncExecutionRecords-CQKzcVFv.js': '/assets/' + freshName } }) + '</script>\n';

// Isolated browser fixtures: every API request is intercepted, never sent to production.
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, proxy: { server: 'http://127.0.0.1:7897' } });
  const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1000 } });
  const errors = [], requests = [];
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/api/')) {
      requests.push(url.pathname + url.search);
      let data = { results: [], options: {}, pagination: { total: 0, page: 1 } };
      if (url.pathname.includes('/auth/me')) data = { id: 1, tenant_id: 1, username: 'browser-fixture', user_type: 'internal', is_superuser: true, permissions: [], roles: [], memberships: [] };
      const source = url.searchParams.get('record_source');
      if (source) data = { results: [{ id: source + '-1', record_source: source, subject_name: 'FIXTURE STORE', platform: 'tiktok', resource_type: source === 'video' ? 'video_metrics' : 'creator_profile', status: source === 'video' ? 'completed' : 'matched', stored_count: source === 'video' ? 2 : 1, evidence_note: 'FIXTURE EVIDENCE', evidence: { fixture: true } }], options: {}, pagination: { total: 1, page: 1 } };
      return route.fulfill({ json: { success: true, code: 'OK', message: 'success', data } });
    }
    if (process.env.CANDIDATE && route.request().isNavigationRequest()) {
      const response = await route.fetch();
      return route.fulfill({ response, body: (await response.text()).replace('<script type="module"', importMap + '<script type="module"') });
    }
    if (process.env.CANDIDATE && url.pathname.endsWith('/' + freshName)) return route.fulfill({ contentType: 'application/javascript', body: candidate });
    // Simulate an old broken asset still cached at the previous URL.
    if (url.pathname.endsWith('/SyncExecutionRecords-CQKzcVFv.js')) return route.fulfill({ contentType: 'application/javascript', body: 'throw new Error("STALE_SYNC_CHUNK_EXECUTED");' });
    if (url.origin !== 'https://xtsy.dingfengchuangyu.com' || !['GET', 'HEAD'].includes(route.request().method())) return route.abort();
    return route.continue();
  });
  await context.addInitScript(() => sessionStorage.setItem('saas-collab.auth.session.v1', JSON.stringify({ access: 'fixture-not-a-token', refresh: 'fixture-not-a-token' })));
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.stack));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  try {
    await page.goto('https://xtsy.dingfengchuangyu.com/integrations/sync-runs', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(5000);
    console.log(JSON.stringify({ phase: 'mounted', url: page.url(), text: (await page.locator('body').innerText()).slice(0, 1800), errors, requests }, null, 2));
    if (process.env.CANDIDATE || process.env.VERIFY_DEPLOYED) {
      for (const label of ['视频采集批次', '达人最新快照']) {
        await page.getByText(label, { exact: true }).click({ timeout: 10000 });
        await page.getByText('FIXTURE EVIDENCE', { exact: true }).waitFor();
        await page.getByText('查看详情', { exact: true }).click();
        await page.getByText('真实采集证据', { exact: true }).waitFor();
        await page.keyboard.press('Escape');
      }
      await page.getByText('系统任务运行', { exact: true }).click();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByText('视频采集批次', { exact: true }).waitFor();
      if (process.env.SCREENSHOT) await page.screenshot({ path: process.env.SCREENSHOT });
      assert.equal(errors.length, 0, errors.join('\n'));
      console.log('PASS: full page render, video/creator tabs, drawers, system tab and reload with old broken chunk isolated.');
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
