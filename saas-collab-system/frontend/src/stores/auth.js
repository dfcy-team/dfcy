import { defineStore } from 'pinia'

import { currentUser } from '../mock'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    currentUser: null,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.currentUser),
  },
  actions: {
    mockLogin() {
      this.currentUser = { ...currentUser }
    },
    logout() {
      this.currentUser = null
    },
  },
})
