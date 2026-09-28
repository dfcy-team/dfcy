import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { safeLocalRedirect, safeSsoCallback } from '../src/utils/ssoRedirect';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('跳转式共用登录', () => {
  it('只接受站内登录返回地址，不接受协议相对或跨站跳转', () => {
    expect(safeLocalRedirect('/sso/authorize?client_id=abc')).toBe('/sso/authorize?client_id=abc');
    for (const bad of ['https://evil.example', '//evil.example', '/\\evil.example', '', null]) expect(safeLocalRedirect(bad)).toBe('/');
  });

  it('调用方回调地址必须是无参数的 HTTPS 地址', () => {
    expect(safeSsoCallback('https://app.example.com/auth/callback')?.pathname).toBe('/auth/callback');
    for (const bad of ['http://app.example.com/auth/callback', 'https://app.example.com/', 'https://u:p@app.example.com/cb', 'https://app.example.com/cb?next=x', 'https://app.example.com/cb#x']) expect(safeSsoCallback(bad)).toBeNull();
  });

  it('管理员单独授权共用登录、配置精确回调，可不授权数据块', () => {
    const page = read('src/views/integrations/AIExternalApiSettings.vue');
    expect(page).toContain('allow_sso_login:form.allow_sso_login');
    expect(page).toContain('sso_redirect_uris:form.allow_sso_login');
    expect(page).toContain('v.length||form.allow_sso_login');
    expect(page).toContain('不接触密码');
    expect(page).toContain('不继承本系统角色或权限');
  });

  it('密码仅在本系统登录页输入，授权页只请求一次性授权码', () => {
    const router = read('src/router/index.js');
    const page = read('src/views/auth/SsoAuthorize.vue');
    expect(router).toContain("path: '/sso/authorize'");
    expect(read('src/router/menu.js')).toContain("{ path: '/sso/authorize', exact: true, userTypes: ['internal'] }");
    expect(router).not.toContain('!to.meta.sso');
    expect(page).toContain('/api/internal/integrations/sso/authorize/');
    expect(page).toContain('target.searchParams.get(\'code\')');
    expect(page).not.toContain('form.password');
    expect(page).not.toContain('v-model="password"');
  });
});
