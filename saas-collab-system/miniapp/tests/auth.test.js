"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createAuthService } = require("../services/auth");

test("platform login sends only the one-time WeChat code to the miniapp auth API", async () => {
  const requests = [];
  let savedSession = null;
  const auth = createAuthService({
    client: {
      async request(options) {
        requests.push(options);
        return {
          access_token: "miniapp-access",
          refresh_token: "miniapp-refresh",
          expires_in: 3600,
          user: { id: "user-001" }
        };
      }
    },
    getConfig: () => ({
      name: "development",
      useMock: false,
      authMode: "platform"
    }),
    platformLogin: async () => "one-time-wechat-code",
    session: {
      setSession(value) {
        savedSession = value;
        return value;
      }
    }
  });

  await auth.login();

  assert.deepEqual(requests, [
    {
      auth: false,
      method: "POST",
      path: "/api/miniapp/auth/login/",
      data: { code: "one-time-wechat-code" }
    }
  ]);
  assert.equal(savedSession.accessToken, "miniapp-access");
  assert.equal(savedSession.refreshToken, "miniapp-refresh");
  assert.equal("session_key" in savedSession, false);
});
