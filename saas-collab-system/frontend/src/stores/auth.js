import { defineStore } from 'pinia';
import { getCurrentUser, login } from '../api/auth';
import { useMock } from '../api/request';
import { clearAuthSession, readAuthSession, writeAuthSession } from '../utils/authSession';
import { mockAuthUser } from '../mock/auth';

export const mockCurrentUser = mockAuthUser;

export const useAuthStore = defineStore('auth', {
  state: () => ({
    currentUser: null,
    isAuthenticated: false,
    initialized: false,
    loading: false,
    errorMessage: ''
  }),
  getters: {
    isInternal: (state) => state.currentUser?.user_type === 'internal',
    isSuperuser: (state) => Boolean(state.currentUser?.is_superuser),
    permissionSet: (state) => new Set(state.currentUser?.permissions || [])
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
      this.isAuthenticated = Boolean(user);
      this.errorMessage = '';
    },
    clearAuthentication(message = '') {
      clearAuthSession();
      this.currentUser = null;
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
    }
  }
});
