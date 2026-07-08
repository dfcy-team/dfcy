import { defineStore } from 'pinia';

export const mockCurrentUser = {
  user_id: 'mock-user-001',
  username: 'stage0_internal_user',
  user_type: 'internal',
  tenant_id: 'mock-tenant-001',
  roles: ['stage0_viewer'],
  permissions: ['mock.view']
};

export const useAuthStore = defineStore('auth', {
  state: () => ({
    currentUser: mockCurrentUser,
    isAuthenticated: true
  }),
  actions: {
    loginWithMock() {
      // 阶段0前端权限仅为展示占位，真实权限以后端 /api/internal/auth/me/ 返回为准。
      this.currentUser = mockCurrentUser;
      this.isAuthenticated = true;
    },
    logout() {
      this.isAuthenticated = false;
    }
  }
});
