import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const frontendRoot = path.resolve(import.meta.dirname, '..');

describe('production login copy', () => {
  it('presents the company and user-facing workspace language', () => {
    const page = fs.readFileSync(path.join(frontendRoot, 'src/views/auth/Login.vue'), 'utf8');
    const html = fs.readFileSync(path.join(frontendRoot, 'index.html'), 'utf8');

    expect(page).toContain('鼎峰创域科技');
    expect(page).toContain('跨境业务协同工作台');
    expect(page).toContain('请使用企业为您分配的账号登录');
    expect(page).toContain('进入工作台');
    expect(html).toContain('<title>业务协同工作台</title>');
  });

  it('does not expose development or architecture terminology', () => {
    const page = fs.readFileSync(path.join(frontendRoot, 'src/views/auth/Login.vue'), 'utf8');

    for (const phrase of ['INTERNAL ACCESS', 'Pilot API', 'Mock', 'JWT', '租户', '后端验证']) {
      expect(page).not.toContain(phrase);
    }
  });
});
