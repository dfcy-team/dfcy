"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { getFoundationCapabilities } = require("../services/capabilities");

function authCapability(config, context) {
  return getFoundationCapabilities(config, context).find(
    (capability) => capability.code === "miniapp_auth"
  );
}

test("platform authentication is connected after a real session is established", () => {
  const capability = authCapability(
    { authMode: "platform", useMock: false },
    { authenticated: true }
  );

  assert.equal(capability.status, "connected");
  assert.match(capability.description, /服务端完成交换/);
});

test("platform authentication remains pending before a session exists", () => {
  const capability = authCapability(
    { authMode: "platform", useMock: false },
    { authenticated: false }
  );

  assert.equal(capability.status, "pending");
});

test("mock authentication remains explicitly labelled as mock", () => {
  const capability = authCapability(
    { authMode: "mock", useMock: true },
    { authenticated: true }
  );

  assert.equal(capability.status, "mock");
});
