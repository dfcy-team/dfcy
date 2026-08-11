"use strict";

const { getFoundationCapabilities } = require("../../services/capabilities");

Page({
  data: {
    capabilities: [],
    environment: "",
    tenantName: "",
    userName: ""
  },

  onShow() {
    const { config, session } = getApp().globalData.services;
    if (!session.isAuthenticated()) {
      wx.reLaunch({ url: "/pages/login/index" });
      return;
    }
    const current = session.getSnapshot();
    this.setData({
      capabilities: getFoundationCapabilities(config, { authenticated: true }),
      environment: config.name,
      tenantName: current.user?.tenant?.name || "未绑定租户",
      userName: current.user?.displayName || "当前用户"
    });
  },

  openStatus() {
    wx.navigateTo({ url: "/pages/status/index" });
  },

  openReleases() {
    wx.navigateTo({ url: "/pages/releases/index" });
  },

  openSupplyOrders() {
    wx.navigateTo({ url: "/pages/supply-orders/index" });
  },

  openConsolidations() {
    wx.navigateTo({ url: "/pages/consolidations/index" });
  },

  handleLogout() {
    getApp().globalData.services.auth.logout();
    wx.reLaunch({ url: "/pages/login/index" });
  }
});
