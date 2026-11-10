const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--no-proxy-server'] });
  const context = await browser.newContext({ serviceWorkers: 'block' });
  let fail = false;
  const errors = [];
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/api/')) {
      if (url.pathname.endsWith('/tiktok-ads/capabilities/')) {
        if (fail) return route.fulfill({ json: { success: false, code:'ERROR', data:null, message: 'timeout of 10000ms exceeded' } });
        return route.fulfill({ json: { success: true, code:'OK', message:'success', data: { items: [{mapping_id:1,store_id:1,store_code:'TK1PH',store_name:'FIXTURE',advertiser_id:'123',advertiser_name:'TEST ACCOUNT',read_enabled:true,can_enable_read:true,verification_state:'verified'}] } } });
      }
      const data = url.pathname.includes('/auth/me') ? {id:1,tenant_id:1,username:'fixture',user_type:'internal',is_superuser:true,permissions:[],roles:[],memberships:[]} : {results:[],items:[],options:{},pagination:{total:0,page:1}};
      return route.fulfill({ json: { success:true, code:'OK', message:'success', data } });
    }
    if (url.origin !== 'https://xtsy.dingfengchuangyu.com' || route.request().method() !== 'GET') return route.abort();
    return route.continue();
  });
  await context.addInitScript(() => sessionStorage.setItem('saas-collab.auth.session.v1',JSON.stringify({access:'fixture',refresh:'fixture'})));
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto('https://xtsy.dingfengchuangyu.com/integrations/capabilities',{waitUntil:'domcontentloaded',timeout:60000});
    await page.waitForTimeout(5000);
    console.log(JSON.stringify({url:page.url(),errors,text:(await page.locator('body').innerText()).slice(0,1200)}));
    await page.getByText('TK 广告',{exact:true}).click();
    await page.getByText('TEST ACCOUNT',{exact:true}).waitFor();
    fail = true;
    await page.getByRole('button',{name:'刷新广告能力',exact:true}).click();
    await page.getByText(/当前保留上次查询结果，操作已暂停/).waitFor();
    assert.equal(await page.getByText('TEST ACCOUNT',{exact:true}).count(),1);
    assert.equal(await page.getByRole('switch').isDisabled(),true);
    fail = false;
    await page.getByRole('button',{name:'刷新广告能力',exact:true}).click();
    await page.getByText(/当前保留上次查询结果，操作已暂停/).waitFor({state:'hidden'});
    assert.equal(errors.length,0,errors.join('\n'));
    console.log('PASS: deployed page mounts; failed refresh preserves rows and disables writes; retry recovers. APIs mocked.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
