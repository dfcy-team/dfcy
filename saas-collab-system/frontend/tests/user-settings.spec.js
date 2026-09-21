import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const frontendRoot = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(frontendRoot, file), 'utf8');

describe('用户个人设置', () => {
  it('在顶部账号区提供个人设置入口', () => {
    const layout = read('src/layouts/MainLayout.vue');

    expect(layout).toContain('userSettingsOpen = true');
    expect(layout).toContain('<UserSettingsDrawer');
    expect(layout).toContain('@profile-updated="handleProfileUpdated"');
    expect(layout).toContain('@password-changed="handlePasswordChanged"');
  });

  it('支持维护个人资料和校验密码', () => {
    const drawer = read('src/components/UserSettingsDrawer.vue');

    for (const phrase of ['个人资料', '修改密码', '登录账号', '当前角色', '姓名', '邮箱', '手机号码']) {
      expect(drawer).toContain(phrase);
    }
    expect(drawer).toContain('autocomplete="current-password"');
    expect(drawer.match(/autocomplete="new-password"/g)).toHaveLength(2);
    expect(drawer).toContain('新密码至少需要 12 位');
    expect(drawer).toContain('value !== passwordForm.new_password');
  });

  it('允许用户设置最大打开页签数', () => {
    const layout = read('src/layouts/MainLayout.vue');
    const drawer = read('src/components/UserSettingsDrawer.vue');

    expect(layout).toContain('const defaultTabLimit = 15;');
    expect(layout).toContain(':tab-limit="tabLimit"');
    expect(layout).toContain('@tab-limit-changed="handleTabLimitChanged"');
    expect(layout).toContain('router.beforeEach');
    expect(layout).toContain('请先关闭不需要的页签后再试');
    expect(drawer).toContain('label="使用偏好"');
    expect(drawer).toContain('label="最大打开页签数"');
    expect(drawer).toContain(':min="5" :max="30"');
    expect(drawer).toContain('默认最多打开 15 个页签');
    expect(drawer).toContain("emit('tab-limit-changed', preferencesForm.tab_limit)");
  });

  it('只调用当前登录用户的自助接口', () => {
    const api = read('src/api/auth.js');

    expect(api).toContain("url: '/api/internal/auth/profile/'");
    expect(api).toContain("method: 'patch'");
    expect(api).toContain("url: '/api/internal/auth/password/'");
    expect(api).toContain("method: 'post'");
    expect(api).not.toMatch(/system\/users\/\$\{/);
  });
});
