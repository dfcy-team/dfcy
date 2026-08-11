"use strict";

const { getMiniAppHealth } = require("../../services/health");

Page({
  data: {
    apiBaseUrl: "",
    backendStatus: "pending",
    environment: "",
    mock: false,
    networkType: "unknown",
    providerExchange: "unknown",
    state: "loading"
  },

  onLoad() {
    const { config } = getApp().globalData.services;
    this.setData({
      apiBaseUrl: config.apiBaseUrl,
      environment: config.name,
      mock: config.useMock
    });
    this.refreshNetwork();
  },

  refreshNetwork() {
    this.setData({ state: "loading" });
    wx.getNetworkType({
      success: async ({ networkType }) => {
        if (networkType === "none") {
          this.setData({
            backendStatus: "unreachable",
            networkType,
            providerExchange: "unavailable",
            state: "offline"
          });
          return;
        }
        const { client, config } = getApp().globalData.services;
        try {
          const health = await getMiniAppHealth(client, config);
          this.setData({
            backendStatus: health.capability_status,
            networkType,
            providerExchange: health.provider_exchange,
            state: "empty"
          });
        } catch (_error) {
          this.setData({
            backendStatus: "degraded",
            networkType,
            providerExchange: "unavailable",
            state: "degraded"
          });
        }
      },
      fail: () => {
        this.setData({
          backendStatus: "unknown",
          networkType: "unknown",
          providerExchange: "unknown",
          state: "degraded"
        });
      }
    });
  }
});
