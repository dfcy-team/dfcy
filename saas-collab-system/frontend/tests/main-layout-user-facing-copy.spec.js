import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), 'src/layouts/MainLayout.vue'), 'utf8');

describe('登录后布局的用户化文案', () => {
  it('在桌面和移动侧栏显示鼎峰创域科技品牌', () => {
    expect(source.match(/<strong>鼎峰创域科技<\/strong>/g)).toHaveLength(2);
    for (const phrase of ['SaaS 协同系统', '厦门市鼎峰科技有限公司', '厦门市鼎峰创域科技有限公司']) {
      expect(source).not.toContain(phrase);
    }
  });

  it('展示账号权限数据中的角色字段，不暴露环境与租户技术信息', () => {
    expect(source).toContain('auth.currentUser?.username');
    expect(source).toContain('auth.currentUser?.roles?.filter(Boolean)');
    expect(source).toContain("roles.length ? roles.join(' / ') : '未分配角色'");
    expect(source).toContain('<span>{{ roleLabel }}</span>');
    expect(source).toContain('个人设置');
    expect(source).toContain('<UserSettingsDrawer');
    expect(source).toContain('退出登录');
    for (const phrase of ['environmentLabel', 'useMock', 'el-tag', 'Pilot API', 'Mock', '租户 {{']) {
      expect(source).not.toContain(phrase);
    }
  });
});
