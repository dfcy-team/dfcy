"use strict";

const { getReleaseWorkbench } = require("../../services/releases");

Page({
  data: {
    errorMessage: "",
    recent: [],
    state: "loading",
    statusCards: [],
    total: 0
  },

  onShow() {
    this.loadWorkbench();
  },

  async loadWorkbench() {
    this.setData({ errorMessage: "", state: "loading" });
    const { client, config } = getApp().globalData.services;
    try {
      const data = await getReleaseWorkbench(client, config);
      if (!data.read_only) {
        throw new Error("发布工作台未声明只读边界");
      }
      const statusCards = Object.keys(data.status_counts || {})
        .sort()
        .map((status) => ({
          count: data.status_counts[status],
          status
        }));
      this.setData({
        recent: data.recent || [],
        state: (data.recent || []).length ? "ready" : "empty",
        statusCards,
        total: data.total || 0
      });
    } catch (error) {
      this.setData({
        errorMessage: error.message || "发布合同加载失败",
        state: "error"
      });
    }
  },

  openContract(event) {
    const id = event.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/release-detail/index?id=${id}` });
  }
});
