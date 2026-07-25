"use strict";

const {
  getMockReleaseContract,
  getMockReleaseWorkbench
} = require("../mock/releases");

async function getReleaseWorkbench(client, config) {
  if (config.useMock) {
    return getMockReleaseWorkbench();
  }
  return client.request({
    method: "GET",
    path: "/api/miniapp/releases/workbench/"
  });
}

async function getReleaseContract(client, config, id) {
  if (config.useMock) {
    return getMockReleaseContract(id);
  }
  return client.request({
    method: "GET",
    path: `/api/miniapp/releases/contracts/${id}/`
  });
}

module.exports = {
  getReleaseContract,
  getReleaseWorkbench
};
