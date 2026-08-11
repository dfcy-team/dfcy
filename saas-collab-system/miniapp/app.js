"use strict";

const { configureRuntime, getConfig } = require("./config/index");
const runtimeEnvironment = require("./config/runtime");
const { createSessionManager } = require("./core/auth/session");
const { createWxStorage, createWxTransport, platformLogin } = require("./core/platform");
const { createRequestClient } = require("./core/request/client");
const { createLogger } = require("./core/telemetry/logger");
const { createAuthService } = require("./services/auth");

App({
  globalData: {
    services: null
  },

  onLaunch() {
    const config = configureRuntime(runtimeEnvironment);
    const logger = createLogger({
      context: {
        app: "saas-collab-system-miniapp",
        environment: config.name
      }
    });
    const session = createSessionManager(createWxStorage());
    session.hydrate();

    let auth;
    const client = createRequestClient({
      getConfig,
      logger,
      refreshSession: () => auth.refresh(),
      session,
      transport: createWxTransport()
    });
    auth = createAuthService({
      client,
      getConfig,
      logger,
      platformLogin,
      session
    });

    this.globalData.services = {
      auth,
      client,
      config,
      logger,
      session
    };
    logger.info("app.launch", {
      authenticated: session.isAuthenticated(),
      mock: config.useMock
    });
  }
});
