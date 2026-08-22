"use strict";

Page({
  data: {
    state: "loading"
  },

  onLoad() {
    const { session } = getApp().globalData.services;
    const target = session.isAuthenticated()
      ? "/pages/home/index"
      : "/pages/login/index";
    wx.reLaunch({ url: target });
  }
});
