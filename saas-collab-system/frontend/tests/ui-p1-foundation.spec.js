import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  readAuthSession,
  updateAccessToken,
  writeAuthSession
} from '../src/utils/authSession';
import { canAccessPath, filterMenuItems, flattenMenuItems, hasRouteCapability } from '../src/router/menu';
import { getActionAccess } from '../src/utils/actionAccess';
import { resolveWorkspace, summarizeDataScope } from '../src/utils/workspace';
import { statusFromApiResponse } from '../src/utils/uiState';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

const financeUser = {
  username: 'finance-user',
  user_type: 'internal',
  is_superuser: false,
  permissions: ['finance.view'],
  roles: ['finance'],
  data_scope: [{ scope_type: 'tenant' }]
};

function authFor(user) {
  return {
    currentUser: user,
    hasPermission: (...codes) => Boolean(user?.is_superuser) || codes.some((code) => (user?.permissions || []).includes(code))
  };
}

describe('UI-P1 session handling', () => {
  beforeEach(() => clearAuthSession());

  it('stores both tokens in sessionStorage and rotates only access', () => {
    writeAuthSession({ access: 'access-one', refresh: 'refresh-one' });
    expect(readAuthSession()).toEqual({ access: 'access-one', refresh: 'refresh-one' });
    expect(getAccessToken()).toBe('access-one');
    expect(getRefreshToken()).toBe('refresh-one');
    expect(updateAccessToken('access-two')).toBe(true);
    expect(readAuthSession()).toEqual({ access: 'access-two', refresh: 'refresh-one' });
  });

  it('clears invalid or explicit sessions', () => {
    window.sessionStorage.setItem('saas-collab.auth.session.v1', '{bad json');
    expect(readAuthSession()).toBeNull();
    writeAuthSession({ access: 'access', refresh: 'refresh' });
    clearAuthSession();
    expect(readAuthSession()).toBeNull();
  });
});

describe('UI-P1 trusted menu and workspace', () => {
  it('shows finance pages only to users with finance permission', () => {
    const paths = flattenMenuItems(filterMenuItems(financeUser)).map((item) => item.path);
    expect(paths).toContain('/finance/analytics');
    expect(paths).not.toContain('/integrations/configs');
    expect(canAccessPath(financeUser, '/finance/statements')).toBe(true);
    expect(canAccessPath(financeUser, '/integrations/configs')).toBe(false);
    expect(canAccessPath(financeUser, '/finance/imports')).toBe(false);
  });

  it('uses a complete default-deny route capability contract', () => {
    const routerSource = read('src/router/index.js');
    const declaredRoutes = [...routerSource.matchAll(/\{ path: '([^']*)', component:/g)]
      .map((match) => match[1])
      .filter((path) => path !== '/login')
      .map((path) => {
        if (!path || path === '/') return '/';
        const absolutePath = path.startsWith('/') ? path : `/${path}`;
        return absolutePath.replace(/:[^/]+/g, 'sample');
      });

    expect(declaredRoutes.length).toBeGreaterThan(40);
    for (const path of declaredRoutes) expect(hasRouteCapability(path), path).toBe(true);
    expect(canAccessPath(financeUser, '/not-registered')).toBe(false);
  });

  it('separates finance import, internal, and external route capabilities', () => {
    const importer = { ...financeUser, permissions: ['finance.import'] };
    const external = { ...financeUser, user_type: 'external', permissions: [] };
    const basicInternal = { ...financeUser, permissions: ['mock.view'] };

    expect(canAccessPath(importer, '/finance/imports')).toBe(true);
    expect(canAccessPath(importer, '/finance/statements')).toBe(false);
    expect(canAccessPath(basicInternal, '/settings/platform-risk')).toBe(false);
    expect(canAccessPath(external, '/suppliers/tasks')).toBe(true);
    expect(canAccessPath(external, '/products/master')).toBe(false);
    expect(canAccessPath(external, '/finance/statements')).toBe(false);
  });

  it('allows the backend-designated superuser to see all menu entries', () => {
    const superuser = { ...financeUser, is_superuser: true, permissions: [], data_scope: [] };
    const paths = flattenMenuItems(filterMenuItems(superuser)).map((item) => item.path);
    expect(paths).toContain('/finance/analytics');
    expect(paths).toContain('/integrations/configs');
    expect(paths).toContain('/settings/config-center');
    expect(summarizeDataScope(superuser)).toBe('全部租户内数据');
  });

  it('selects a finance workspace from trusted permissions', () => {
    expect(resolveWorkspace(financeUser).key).toBe('finance');
    expect(summarizeDataScope(financeUser)).toBe('tenant');
  });
});

describe('UI-P1 action permission convergence', () => {
  const viewOnlyUser = {
    ...financeUser,
    permissions: [
      'alerts.view',
      'config.view',
      'finance.view',
      'integrations.view',
      'products.lifecycle.view',
      'products.status.view',
      'replenishment.view',
      'reports.view'
    ]
  };

  it.each([
    ['review', 'replenishment.review'],
    ['lifecycle confirmation', 'products.lifecycle.confirm'],
    ['alert management', 'alerts.manage'],
    ['configuration management', 'config.manage'],
    ['configuration rollback', 'config.rollback'],
    ['report export', 'reports.export'],
    ['finance reconciliation', 'finance.reconcile'],
    ['integration execution', 'integrations.run']
  ])('hides %s actions from view-only users', (_label, permission) => {
    expect(getActionAccess(authFor(viewOnlyUser), { permission })).toEqual({
      allowed: false,
      visible: false,
      disabled: true,
      reason: `缺少操作权限：${permission}`
    });
  });

  it('allows an action only after the backend action permission is present', () => {
    const reviewer = { ...viewOnlyUser, permissions: [...viewOnlyUser.permissions, 'replenishment.review'] };
    expect(getActionAccess(authFor(reviewer), { permission: 'replenishment.review' }).allowed).toBe(true);
    expect(getActionAccess(authFor(reviewer), { permission: 'reports.export' }).allowed).toBe(false);
  });

  it('supports an explicit disabled-with-reason presentation without allowing execution', () => {
    const access = getActionAccess(authFor(viewOnlyUser), {
      permission: 'config.approve',
      unauthorizedBehavior: 'disable'
    });
    expect(access.allowed).toBe(false);
    expect(access.visible).toBe(true);
    expect(access.disabled).toBe(true);
    expect(access.reason).toContain('config.approve');
  });

  it('binds every executable shared-page action to its backend permission code', () => {
    const expectedContracts = {
      'src/views/inventory/ReplenishmentSuggestionList.vue': 'replenishment.review',
      'src/views/lifecycle/LifecycleReviewList.vue': 'products.lifecycle.confirm',
      'src/views/alerts/BusinessAlertList.vue': 'alerts.manage',
      'src/views/settings/ConfigCenterList.vue': 'config.manage',
      'src/views/settings/ConfigVersionHistory.vue': 'config.rollback',
      'src/views/reports/ReportExportCenter.vue': 'reports.export',
      'src/views/finance/ReconciliationMatchList.vue': 'finance.reconcile',
      'src/views/finance/ReconciliationMatchDetail.vue': 'finance.reconcile',
      'src/views/products/ProductStatusRecommendationDetail.vue': 'products.status.confirm',
      'src/views/integrations/SyncJobList.vue': 'integrations.run'
    };
    for (const [path, permission] of Object.entries(expectedContracts)) {
      expect(read(path), path).toContain(`permission: '${permission}'`);
    }

    for (const component of ['src/components/Phase2DataPage.vue', 'src/components/Phase3DecisionPage.vue']) {
      const source = read(component);
      expect(source).toContain('getActionAccess(auth, action)');
      expect(source).toContain('if (!access.allowed)');
    }
  });
});

describe('UI-P1 complete page states', () => {
  it.each([
    [{ success: false, http_status: 403 }, true, 'forbidden'],
    [{ success: false, http_status: 404 }, true, 'empty'],
    [{ success: false, http_status: 409 }, true, 'conflict'],
    [{ success: false, http_status: 422 }, true, 'invalid'],
    [{ success: true, data: { partial: true } }, true, 'partial'],
    [{ success: false }, false, 'offline']
  ])('maps API response %j to %s', (response, online, expected) => {
    expect(statusFromApiResponse(response, online)).toBe(expected);
  });

  it('declares every required visual state', () => {
    const source = read('src/components/AppState.vue');
    for (const state of ['loading', 'empty', 'error', 'forbidden', 'conflict', 'invalid', 'partial', 'offline']) {
      expect(source).toContain(`${state}:`);
    }
  });
});

describe('UI-P1 authentication source contracts', () => {
  it('attaches Bearer auth and performs one controlled refresh path', () => {
    const source = read('src/api/request.js');
    expect(source).toContain('config.headers.Authorization = `Bearer ${access}`');
    expect(source).toContain('refreshPromise ||= axios');
    expect(source).toContain('/api/internal/auth/refresh/');
    expect(source).toContain('clearAuthSession()');
  });

  it('does not default production state to an authenticated mock user', () => {
    const source = read('src/stores/auth.js');
    expect(source).toContain('currentUser: null');
    expect(source).toContain('isAuthenticated: false');
    expect(source).not.toContain('loginWithMock');
  });

  it('uses real credentials and a route authentication gate', () => {
    const login = read('src/views/auth/Login.vue');
    const router = read('src/router/index.js');
    expect(login).toContain('autocomplete="username"');
    expect(login).toContain('autocomplete="current-password"');
    expect(router).toContain('await auth.initialize()');
    expect(router).toContain("path: '/login'");
    expect(router).toContain("return '/forbidden'");
  });
});
