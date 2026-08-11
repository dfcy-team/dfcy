"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createSessionManager } = require("../core/auth/session");

function createMemoryStorage(initial) {
  const values = new Map(initial ? [["miniapp.session.v1", initial]] : []);
  return {
    get: (key) => values.get(key),
    set: (key, value) => values.set(key, value),
    remove: (key) => values.delete(key)
  };
}

test("session hydrates, persists and clears", () => {
  const storage = createMemoryStorage();
  const session = createSessionManager(storage);
  session.setSession({
    accessToken: "access",
    refreshToken: "refresh",
    expiresAt: Date.now() + 60000,
    user: { id: "u1" }
  });

  const restored = createSessionManager(storage);
  restored.hydrate();
  assert.equal(restored.isAuthenticated(), true);
  assert.equal(restored.getSnapshot().user.id, "u1");

  restored.clear();
  assert.equal(restored.isAuthenticated(), false);
  assert.equal(restored.getAccessToken(), "");
});

test("expired session is not authenticated", () => {
  const session = createSessionManager(createMemoryStorage());
  session.setSession({
    accessToken: "expired",
    expiresAt: Date.now() - 1
  });
  assert.equal(session.isAuthenticated(), false);
});

test("missing access token is rejected", () => {
  const session = createSessionManager(createMemoryStorage());
  assert.throws(() => session.setSession({ refreshToken: "only" }), /缺少访问令牌/);
});
