"use strict";

async function getMiniAppHealth(client, config) {
  if (config.useMock) {
    return {
      service: "miniapp-auth",
      capability_status: "mock",
      provider_exchange: "local-mock"
    };
  }
  return client.request({
    auth: false,
    method: "GET",
    path: "/api/miniapp/health/",
    retry: false
  });
}

module.exports = {
  getMiniAppHealth
};
