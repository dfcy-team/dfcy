"use strict";

Page({
  data: {
    environment: "",
    errorMessage: "",
    loading: false,
    mock: false
  },

  onLoad() {
    const { config, session } = getApp().globalData.services;
    if (session.isAuthenticated()) {
      wx.reLaunch({ url: "/pages/home/index" });
      return;
    }
    this.setData({
      environment: config.name,
      mock: config.useMock
    });
  },

  async handleLogin() {
    if (this.data.loading) {
      return;
    }
    this.setData({ errorMessage: "", loading: true });
    try {
      await getApp().globalData.services.auth.login();
      wx.reLaunch({ url: "/pages/home/index" });
    } catch (error) {
      const { config } = getApp().globalData.services;
      const reason =
        config.name !== "production" && error?.details?.reason
          ? `（诊断：${error.details.reason}）`
          : "";
      this.setData({
        errorMessage: `${error.message || "登录失败，请稍后重试"}${reason}`
      });
    } finally {
      this.setData({ loading: false });
    }
  }
});
