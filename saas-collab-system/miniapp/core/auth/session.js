"use strict";

const { AuthError } = require("../errors");

const SESSION_STORAGE_KEY = "miniapp.session.v1";

function emptySession() {
  return {
    accessToken: "",
    refreshToken: "",
    expiresAt: 0,
    user: null
  };
}

function normalizeSession(input = {}) {
  const accessToken = String(input.accessToken || input.access || "");
  const refreshToken = String(input.refreshToken || input.refresh || "");
  const expiresAt = Number(input.expiresAt || 0);
  return {
    accessToken,
    refreshToken,
    expiresAt: Number.isFinite(expiresAt) ? expiresAt : 0,
    user: input.user || null
  };
}

function createSessionManager(storage, options = {}) {
  if (!storage) {
    throw new Error("Session storage adapter is required.");
  }
  const storageKey = options.storageKey || SESSION_STORAGE_KEY;
  let state = emptySession();

  function hydrate() {
    try {
      const saved = storage.get(storageKey);
      state = saved ? normalizeSession(saved) : emptySession();
    } catch (_error) {
      state = emptySession();
    }
    return getSnapshot();
  }

  function setSession(nextSession) {
    const normalized = normalizeSession(nextSession);
    if (!normalized.accessToken) {
      throw new AuthError("登录响应缺少访问令牌", { code: "AUTH_TOKEN_MISSING" });
    }
    state = normalized;
    storage.set(storageKey, state);
    return getSnapshot();
  }

  function clear() {
    state = emptySession();
    storage.remove(storageKey);
  }

  function isAuthenticated(now = Date.now()) {
    if (!state.accessToken) {
      return false;
    }
    return !state.expiresAt || state.expiresAt > now + 30000;
  }

  function getSnapshot() {
    return {
      accessToken: state.accessToken,
      refreshToken: state.refreshToken,
      expiresAt: state.expiresAt,
      user: state.user ? { ...state.user } : null
    };
  }

  return {
    clear,
    getAccessToken: () => state.accessToken,
    getRefreshToken: () => state.refreshToken,
    getSnapshot,
    hydrate,
    isAuthenticated,
    setSession
  };
}

module.exports = {
  SESSION_STORAGE_KEY,
  createSessionManager,
  normalizeSession
};
