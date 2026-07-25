"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  ENVIRONMENTS,
  assertRuntimeConfig,
  configureRuntime,
  getConfig,
  setEnvironment
} = require("../config");

test("development is mock-first and production fails closed", () => {
  setEnvironment("development");
  assert.equal(getConfig().useMock, true);
  assert.equal(ENVIRONMENTS.production.useMock, false);
  assert.match(ENVIRONMENTS.production.apiBaseUrl, /^https:\/\//);
  assert.equal(assertRuntimeConfig(ENVIRONMENTS.production), true);
});

test("unknown environment is rejected", () => {
  assert.throws(() => setEnvironment("unknown"), /Unknown miniapp environment/);
  setEnvironment("development");
});

test("non-development environment must use HTTPS", () => {
  assert.throws(
    () =>
      assertRuntimeConfig({
        name: "preview",
        apiBaseUrl: "http://preview.example.invalid",
        useMock: false
      }),
    /must use HTTPS/
  );
});

test("runtime can opt into a local backend sandbox without storing credentials", () => {
  const config = configureRuntime({
    environment: "development",
    useMock: false,
    authMode: "sandbox",
    sandboxSubject: "device-001"
  });
  assert.equal(config.apiBaseUrl, "http://localhost:8000");
  assert.equal(config.authMode, "sandbox");
  assert.equal(config.useMock, false);
  setEnvironment("development");
});

test("development can opt into the real platform exchange without client secrets", () => {
  const config = configureRuntime({
    environment: "development",
    apiBaseUrl: "http://127.0.0.1:8000",
    useMock: false,
    authMode: "platform"
  });
  assert.equal(config.authMode, "platform");
  assert.equal(config.useMock, false);
  assert.equal("appSecret" in config, false);
  setEnvironment("development");
});

test("production cannot be overridden to sandbox authentication", () => {
  assert.throws(
    () =>
      configureRuntime({
        environment: "production",
        authMode: "sandbox",
        sandboxSubject: "device-001"
      }),
    /Production must use/
  );
  setEnvironment("development");
});
