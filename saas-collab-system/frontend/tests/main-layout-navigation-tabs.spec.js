import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), 'src/layouts/MainLayout.vue'), 'utf8');

describe('MainLayout navigation shell', () => {
  it('keeps the desktop sidebar fixed while only its menu list scrolls', () => {
    expect(source).toContain('class="sidebar-menu-scroll"');
    expect(source).toContain('position: fixed;');
    expect(source).toContain('height: 100vh;');
    expect(source).toContain('overflow-y: auto; overflow-x: hidden;');
    expect(source).toContain('margin-left: 248px;');
  });

  it('tracks route-driven tabs with activation, close, and native drag reorder', () => {
    expect(source).toContain('role="tablist"');
    expect(source).toContain('watch(() => route.fullPath');
    expect(source).toContain('@dragstart="startTabDrag(tab.path, $event)"');
    expect(source).toContain('@drop.prevent="dropTab(tab.path)"');
    expect(source).toContain('function closeTab(path)');
    expect(source).toContain("if (index < 0 || path === '/') return;");
    expect(source).toContain("const nextTab = openTabs.value[Math.max(0, index - 1)] || openTabs.value[0];");
    expect(source).toContain("const tabsStorageKey = 'business-workbench:open-tabs';");
    expect(source).toContain('const openTabs = ref(loadOpenTabs());');
    expect(source).toContain('sessionStorage.setItem(tabsStorageKey, JSON.stringify(tabs));');
  });

  it('shows position-aware controls for the main content scroll container', () => {
    expect(source).toContain('ref="mainScrollContainer"');
    expect(source).toContain('@scroll="updateScrollControls"');
    expect(source).toContain('v-if="canScrollUp"');
    expect(source).toContain('v-if="canScrollDown"');
    expect(source).toContain('aria-label="回到顶部"');
    expect(source).toContain('aria-label="滚动到底部"');
    expect(source).toContain('scrollHeight - 4');
    expect(source).toContain('position: fixed; z-index: 30; right: 18px; bottom: 18px;');
    expect(source).toContain('new MutationObserver');
    expect(source).toContain('mainScrollContainer.value?.$el || mainScrollContainer.value');
  });
});
