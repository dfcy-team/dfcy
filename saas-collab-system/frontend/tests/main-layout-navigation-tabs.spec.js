import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick, reactive } from 'vue';

const harness = vi.hoisted(() => ({ route: null, auth: null, router: null }));

vi.mock('vue-router', () => ({
  useRoute: () => harness.route,
  useRouter: () => harness.router
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => harness.auth }));
vi.mock('../src/api/request', () => ({ useMock: true }));
vi.mock('../src/api/authorization', () => ({ fetchAuthorizationVersion: vi.fn() }));
vi.mock('../src/components/UserSettingsDrawer.vue', async () => {
  const { defineComponent } = await import('vue');
  return { default: defineComponent({ template: '<div />' }) };
});

import MainLayout from '../src/layouts/MainLayout.vue';

const source = readFileSync(resolve(process.cwd(), 'src/layouts/MainLayout.vue'), 'utf8');

const storedSalesTabs = [
  { path: '/sales-management/stores', label: '门店销售', closable: true },
  { path: '/sales-management/skus', label: 'SKU销售', closable: true }
];

function mountMainLayout(path) {
  sessionStorage.setItem('business-workbench:open-tabs', JSON.stringify(storedSalesTabs));
  harness.route = reactive({ path, fullPath: path });
  harness.router = {
    beforeEach: vi.fn(() => vi.fn()),
    push: vi.fn(async (nextPath) => {
      harness.route.path = nextPath;
      harness.route.fullPath = nextPath;
      return undefined;
    }),
    replace: vi.fn()
  };
  harness.auth = reactive({
    currentUser: {
      user_type: 'internal',
      username: 'sales-viewer',
      full_name: 'Sales Viewer',
      permissions: [
        'sales_management.view', 'sales_management.orders.view', 'sales_management.returns.view',
        'sales_management.stores.view', 'sales_management.skus.view', 'sales_management.export',
        'sales_management.data_quality.view', 'sales_management.sync.view'
      ],
      roles: ['销售人员'],
      org_memberships: []
    },
    isAuthenticated: true,
    authorizationStale: false,
    logout: vi.fn(),
    setCurrentUser: vi.fn(),
    refreshCurrentUser: vi.fn()
  });
  return mount(MainLayout, {
    global: {
      mocks: { $route: harness.route, $router: harness.router },
      stubs: { 'router-view': true }
    }
  });
}

afterEach(() => {
  sessionStorage.clear();
  document.body.innerHTML = '';
});

describe('MainLayout navigation shell', () => {
  it.each([
    ['/sales-management/stores', '门店销售', 'sales_management.stores.view'],
    ['/sales-management/skus', 'SKU销售', 'sales_management.skus.view']
  ])('renders the authorized hidden page tab for %s and removes it after access is revoked', async (path, label, permission) => {
    const wrapper = mountMainLayout(path);
    try {
      await nextTick();
      await nextTick();

      const activeTab = wrapper.find('[role="tab"][aria-selected="true"]');
      expect(activeTab.exists()).toBe(true);
      expect(activeTab.text()).toBe(label);
      expect(wrapper.find('.header-context').text()).toContain(label);
      expect(wrapper.find('.sidebar-menu-scroll').text()).not.toContain('门店销售');
      expect(wrapper.find('.sidebar-menu-scroll').text()).not.toContain('SKU销售');
      expect(wrapper.find('.sidebar-menu-scroll').text()).toContain('退款退货');
      expect(wrapper.find('.route-tabs').text()).toContain('门店销售');
      expect(wrapper.find('.route-tabs').text()).toContain('SKU销售');
      expect(JSON.parse(sessionStorage.getItem('business-workbench:open-tabs')))
        .toEqual(expect.arrayContaining(storedSalesTabs));

      harness.auth.currentUser.permissions = harness.auth.currentUser.permissions.filter((code) => code !== permission);
      await nextTick();
      await nextTick();

      expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).not.toContain(label);
      const persistedTabs = JSON.parse(sessionStorage.getItem('business-workbench:open-tabs'));
      expect(persistedTabs.map((tab) => tab.path)).not.toContain(path);
      expect(persistedTabs.map((tab) => tab.path)).toContain(
        path.endsWith('/stores') ? '/sales-management/skus' : '/sales-management/stores'
      );
    } finally {
      wrapper.unmount();
    }
  });

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

  it('resolves titles and tabs from the full authorized menu while rendering a filtered sidebar', () => {
    expect(source).toContain('const authorizedMenuItems = computed(() => filterMenuItems(auth.currentUser));');
    expect(source).toContain('const authorizedMenuEntries = computed(() => flattenMenuItems(authorizedMenuItems.value));');
    expect(source).toContain('const sidebarMenuItems = computed(() => filterSidebarMenuItems(auth.currentUser));');
    expect(source.match(/<AppMenu :items="sidebarMenuItems"/g)).toHaveLength(2);
    expect(source).toContain('function resolveMenuTab(path)');
    expect(source).toContain('return authorizedMenuEntries.value');
    expect(source).toContain('routePath.startsWith(`${item.path}/`)');
    expect(source).toContain('const menuTab = resolveMenuTab(currentRoute.path);');
    expect(source).toContain('if (!menuTab)');
    expect(source).toContain('label: menuTab.label');
    expect(source).toContain("allowedPaths.has(tab.path)");
    expect(source).toContain('watch(authorizedMenuEntries, (menuEntries) =>');
    expect(source).toContain("activeMenuTabPath === tab.path");
  });

  it('limits new tabs with a per-user preference and defaults to 15', () => {
    expect(source).toContain('const defaultTabLimit = 15;');
    expect(source).toContain('business-workbench:tab-limit:');
    expect(source).toContain('if (!menuTab) return true;');
    expect(source).toContain('openTabs.value.length < tabLimit.value');
    expect(source).toContain('最多可打开 ${tabLimit.value} 个页签');
    expect(source).toContain("cancelButtonText: '自行关闭'");
    expect(source).toContain("confirmButtonText: '清空后打开'");
    expect(source).toContain('openTabs.value = [homeTab];');
    expect(source).toContain('return false;');
    expect(source).toContain('const navigationFailure = await router.push(item.path);');
    expect(source).toContain('if (navigationFailure) menuRenderVersion.value += 1;');
  });

  it('can clear all closable tabs while preserving the workbench', () => {
    expect(source).toContain('v-if="openTabs.length > 1"');
    expect(source).toContain('@click="clearAllTabs"');
    expect(source).toContain('title="关闭全部页签，保留工作台"');
    expect(source).toContain('async function clearAllTabs()');
    expect(source).toContain("const navigationFailure = await router.push('/');");
    expect(source).toContain('openTabs.value = [homeTab];');
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
