import { defineStore } from 'pinia';
import { getCurrentUser, login } from '../api/auth';
import { useMock } from '../api/request';
import { clearAuthSession, readAuthSession, writeAuthSession } from '../utils/authSession';
import { mockAuthUser } from '../mock/auth';

export const mockCurrentUser = mockAuthUser;

export const useAuthStore = defineStore('auth', {
  state: () => ({
    currentUser: null,
    moduleStatuses: {},
    isAuthenticated: false,
    initialized: false,
    loading: false,
    errorMessage: ''
  }),
  getters: {
    isInternal: (state) => state.currentUser?.user_type === 'internal',
    isSuperuser: (state) => Boolean(state.currentUser?.is_superuser),
    permissionSet: (state) => {
      const user = state.currentUser;
      return new Set([
        ...(user?.permissions || []),
        ...(user?.action_permission_codes || []),
      ]);
    },
    menuPermissionSet: (state) => {
      const user = state.currentUser;
      return Array.isArray(user?.menu_permission_codes) ? new Set(user.menu_permission_codes) : null;
    },
    actionPermissionSet: (state) => {
      const user = state.currentUser;
      return Array.isArray(user?.action_permission_codes)
        ? new Set(user.action_permission_codes)
        : new Set(user?.permissions || []);
    },
    fieldPermissionSet: (state) => {
      const user = state.currentUser;
      return Array.isArray(user?.field_permission_codes) ? new Set(user.field_permission_codes) : null;
    },
    isModuleEnabled: (state) => (code) => {
      const status = state.moduleStatuses?.[code];
      // Older sessions/users do not have module status yet; preserve the
      // legacy all-enabled behaviour until the next /auth/me response.
      return !status || status === 'enabled' || status === 'pilot_readonly';
    }
  },
  actions: {
    async initialize() {
      if (this.initialized) return this.isAuthenticated;
      if (useMock) {
        this.setCurrentUser(mockCurrentUser);
        this.initialized = true;
        return true;
      }
      if (!readAuthSession()) {
        this.initialized = true;
        return false;
      }
      const response = await getCurrentUser();
      if (response.success) this.setCurrentUser(response.data);
      else this.clearAuthentication(response.message);
      this.initialized = true;
      return this.isAuthenticated;
    },
    async login(credentials) {
      this.loading = true;
      this.errorMessage = '';
      try {
        const response = await login(credentials);
        if (!response.success) {
          this.clearAuthentication(response.message);
          return response;
        }
        if (!useMock) {
          writeAuthSession({ access: response.data.access, refresh: response.data.refresh });
        }
        const meResponse = useMock
          ? { success: true, data: mockCurrentUser }
          : await getCurrentUser();
        if (!meResponse.success) {
          this.clearAuthentication(meResponse.message);
          return meResponse;
        }
        this.setCurrentUser(meResponse.data);
        this.initialized = true;
        return { success: true, code: 'OK', message: 'success', data: meResponse.data };
      } finally {
        this.loading = false;
      }
    },
    setCurrentUser(user) {
      this.currentUser = user;
      this.moduleStatuses = user?.module_statuses || user?.modules || {};
      this.isAuthenticated = Boolean(user);
      this.errorMessage = '';
    },
    clearAuthentication(message = '') {
      clearAuthSession();
      this.currentUser = null;
      this.moduleStatuses = {};
      this.isAuthenticated = false;
      this.errorMessage = message;
    },
    logout() {
      this.clearAuthentication();
      this.initialized = true;
    },
    hasPermission(...codes) {
      if (this.isSuperuser) return true;
      return codes.some((code) => this.permissionSet.has(code));
    },
    hasMenuPermission(...codes) {
      if (this.isSuperuser) return true;
      const source = this.menuPermissionSet || this.permissionSet;
      return codes.some((code) => source.has(code));
    },
    hasActionPermission(...codes) {
      if (this.isSuperuser) return true;
      return codes.some((code) => this.actionPermissionSet.has(code));
    },
    hasFieldPermission(...codes) {
      if (this.isSuperuser) return true;
      const source = this.fieldPermissionSet;
      if (!source) return true;
      const granted = [...source];
      const resourceOf = (code) => {
        const parts = String(code || '').split('.');
        return parts[0] === 'field' ? parts[2] || '' : '';
      };
      // Empty grants from a legacy role are compatible by resource: a users
      // allow-list must not hide tenant/role columns, and a grant in one
      // resource activates deny-by-default only for that same resource.
      return codes.some((code) => {
        const resource = resourceOf(code);
        const resourceGrants = granted.filter((item) => resourceOf(item) === resource);
        return resourceGrants.length === 0 || source.has(code);
      });
    }
  }
});
