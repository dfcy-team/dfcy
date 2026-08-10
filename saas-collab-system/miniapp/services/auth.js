"use strict";

const { AuthError } = require("../core/errors");
const { createMockSession } = require("../mock/auth");

function mapSession(payload) {
  return {
    accessToken: payload.access_token || payload.accessToken || "",
    refreshToken: payload.refresh_token || payload.refreshToken || "",
    expiresAt: payload.expires_at
      ? new Date(payload.expires_at).getTime()
      : Date.now() + Number(payload.expires_in || 3600) * 1000,
    user: payload.user || null
  };
}

function createAuthService(options) {
  const { client, getConfig, logger, platformLogin, session } = options;

  async function login() {
    const config = getConfig();
    let nextSession;
    if (config.useMock) {
      nextSession = createMockSession();
      logger?.info("auth.login.mock", { environment: config.name });
    } else {
      if (config.authMode === "disabled") {
        throw new AuthError("当前环境未启用小程序认证", {
          code: "MINIAPP_AUTH_DISABLED"
        });
      }
      const code =
        config.authMode === "sandbox"
          ? `sandbox:${config.sandboxSubject}`
          : await platformLogin();
      const payload = await client.request({
        auth: false,
        method: "POST",
        path: "/api/miniapp/auth/login/",
        data: { code }
      });
      nextSession = mapSession(payload);
    }
    return session.setSession(nextSession);
  }

  async function refresh() {
    const refreshToken = session.getRefreshToken();
    if (!refreshToken) {
      throw new AuthError("缺少刷新令牌，请重新登录");
    }
    if (getConfig().useMock) {
      const current = session.getSnapshot();
      return session.setSession({
        ...current,
        accessToken: "mock-access-token-refreshed",
        expiresAt: Date.now() + 60 * 60 * 1000
      });
    }
    const payload = await client.request({
      auth: false,
      method: "POST",
      path: "/api/miniapp/auth/refresh/",
      data: { refresh_token: refreshToken }
    });
    const current = session.getSnapshot();
    const refreshed = mapSession(payload);
    return session.setSession({
      ...current,
      ...refreshed,
      refreshToken: refreshed.refreshToken || current.refreshToken,
      user: refreshed.user || current.user
    });
  }

  async function loadCurrentUser() {
    if (getConfig().useMock) {
      return session.getSnapshot().user;
    }
    const user = await client.request({
      method: "GET",
      path: "/api/miniapp/auth/me/"
    });
    const current = session.getSnapshot();
    session.setSession({ ...current, user });
    return user;
  }

  function logout() {
    session.clear();
    logger?.info("auth.logout");
  }

  return {
    loadCurrentUser,
    login,
    logout,
    refresh
  };
}

module.exports = {
  createAuthService,
  mapSession
};
