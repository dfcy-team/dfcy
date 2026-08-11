"use strict";

function createMockSession() {
  return {
    accessToken: "mock-access-token",
    refreshToken: "mock-refresh-token",
    expiresAt: Date.now() + 60 * 60 * 1000,
    user: {
      id: "mock-user-001",
      displayName: "演示用户",
      tenant: {
        id: "mock-tenant-001",
        name: "演示租户"
      },
      roles: ["miniapp_viewer"],
      permissions: ["miniapp.home.view"],
      dataScope: "self"
    }
  };
}

module.exports = {
  createMockSession
};
