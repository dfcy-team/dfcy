import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), 'src/layouts/MainLayout.vue'), 'utf8');

describe('MainLayout dark navigation theme', () => {
  it('uses the same dark navigation surface for desktop and mobile menus', () => {
    expect(source).toContain('class="navigation-surface"');
    expect(source).toContain('class="navigation-drawer"');
    expect(source).toContain('<AppMenu :items="visibleMenuItems" />');
    expect(source).toContain('<AppMenu :items="visibleMenuItems" @select="mobileMenuOpen = false" />');
  });

  it('declares readable dark menu states without changing menu data or routing', () => {
    for (const color of ['#101827', '#0b1220', '#1e293b', '#1d4ed8', '#1e40af', '#cbd5e1', '#f8fafc']) {
      expect(source).toContain(color);
    }
    for (const contract of [
      '--el-menu-active-color',
      '--el-menu-hover-bg-color',
      'el-sub-menu__icon-arrow',
      'el-sub-menu.is-opened',
      'el-menu-item.is-active'
    ]) {
      expect(source).toContain(contract);
    }
    expect(source).toContain(':global(.navigation-drawer)');
    expect(source).toContain(':global(.navigation-drawer .el-drawer__body)');
    expect(source).toContain("filterMenuItems(auth.currentUser)");
    expect(source).toContain("router: true");
  });
});
