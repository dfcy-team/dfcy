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

  it('creates tabs only from visible left-menu entries', () => {
    expect(source).toContain('flattenMenuItems(visibleMenuItems.value)');
    expect(source).toContain('function resolveMenuTab(path)');
    expect(source).toContain('routePath.startsWith(`${item.path}/`)');
    expect(source).toContain('const menuTab = resolveMenuTab(currentRoute.path);');
    expect(source).toContain('if (!menuTab)');
    expect(source).toContain('label: menuTab.label');
    expect(source).toContain("allowedPaths.has(tab.path)");
    expect(source).toContain("activeMenuTabPath === tab.path");
  });

  it('limits new tabs with a per-user preference and defaults to 15', () => {
    expect(source).toContain('const defaultTabLimit = 15;');
    expect(source).toContain('business-workbench:tab-limit:');
    expect(source).toContain('if (!menuTab) return true;');
    expect(source).toContain('openTabs.value.length < tabLimit.value');
    expect(source).toContain('最多可打开 ${tabLimit.value} 个页签');
    expect(source).toContain('return false;');
    expect(source).toContain('const navigationFailure = await router.push(item.path);');
    expect(source).toContain('if (navigationFailure) menuRenderVersion.value += 1;');
  });

  it('renders the tab strip as left-aligned compact buttons', () => {
    expect(source).toContain('class="header-primary"');
    expect(source).toContain('justify-content: flex-start;');
    expect(source).toContain('border-radius: 5px;');
    expect(source).toContain('background: linear-gradient(#fff, #f3f4f6);');
    expect(source).toContain('background: #334155; font-weight: 600;');
    expect(source).toContain('height: calc(100vh - 104px);');
  });

  it('explains tab move and close interactions on hover', () => {
    expect(source).toContain('可以移动TAB页，可以关闭TAB页');
    expect(source).toContain('可以移动TAB页，固定页签不可关闭');
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
