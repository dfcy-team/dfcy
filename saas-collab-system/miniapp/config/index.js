"use strict";

const ENVIRONMENTS = Object.freeze({
  development: Object.freeze({
    name: "development",
    apiBaseUrl: "http://localhost:8000",
    authMode: "mock",
    sandboxSubject: "",
    useMock: true,
    requestTimeoutMs: 10000,
    logLevel: "debug"
  }),
  test: Object.freeze({
    name: "test",
    apiBaseUrl: "https://test-api.example.invalid",
    authMode: "sandbox",
    sandboxSubject: "device-001",
    useMock: false,
    requestTimeoutMs: 10000,
    logLevel: "info"
  }),
  preview: Object.freeze({
    name: "preview",
    apiBaseUrl: "https://preview-api.example.invalid",
    authMode: "disabled",
    sandboxSubject: "",
    useMock: false,
    requestTimeoutMs: 10000,
    logLevel: "info"
  }),
  production: Object.freeze({
    name: "production",
    apiBaseUrl: "https://api.example.invalid",
    authMode: "platform",
    sandboxSubject: "",
    useMock: false,
    requestTimeoutMs: 10000,
    logLevel: "warn"
  })
});

let activeEnvironment = "development";
let runtimeOverrides = {};

function getConfig() {
  return Object.freeze({
    ...ENVIRONMENTS[activeEnvironment],
    ...runtimeOverrides
  });
}

function setEnvironment(name) {
  if (!Object.prototype.hasOwnProperty.call(ENVIRONMENTS, name)) {
    throw new Error(`Unknown miniapp environment: ${name}`);
  }
  activeEnvironment = name;
  runtimeOverrides = {};
  return getConfig();
}

function assertRuntimeConfig(config = getConfig()) {
  if (config.name === "production" && config.useMock) {
    throw new Error("Production must not enable Mock mode.");
  }
  if (!/^https?:\/\//.test(config.apiBaseUrl)) {
    throw new Error("API base URL must use http or https.");
  }
  if (config.name !== "development" && !config.apiBaseUrl.startsWith("https://")) {
    throw new Error("Non-development environments must use HTTPS.");
  }
  if (
    config.name === "production" &&
    ["mock", "sandbox"].includes(config.authMode)
  ) {
    throw new Error("Production must use the reviewed platform authentication mode.");
  }
  if (config.authMode === "sandbox" && !config.sandboxSubject) {
    throw new Error("Sandbox authentication requires a pre-bound subject.");
  }
  return true;
}

function configureRuntime(runtime = {}) {
  setEnvironment(runtime.environment || "development");
  const allowedOverrides = [
    "apiBaseUrl",
    "authMode",
    "sandboxSubject",
    "useMock"
  ];
  runtimeOverrides = allowedOverrides.reduce((output, key) => {
    if (Object.prototype.hasOwnProperty.call(runtime, key)) {
      output[key] = runtime[key];
    }
    return output;
  }, {});
  const config = getConfig();
  assertRuntimeConfig(config);
  return config;
}

module.exports = {
  ENVIRONMENTS,
  assertRuntimeConfig,
  configureRuntime,
  getConfig,
  setEnvironment
};
