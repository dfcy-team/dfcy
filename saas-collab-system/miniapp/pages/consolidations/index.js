"use strict";

const { getAssignments } = require("../../services/consolidations");

Page({
  data: { assignments: [], errorMessage: "", state: "loading" },

  onShow() { return this.loadAssignments(); },
  onPullDownRefresh() { return this.loadAssignments().finally(() => wx.stopPullDownRefresh()); },

  async loadAssignments() {
    this.setData({ state: "loading", errorMessage: "" });
    const { client, config } = getApp().globalData.services;
    try {
      const data = await getAssignments(client, config, { page: 1, page_size: 50 });
      const assignments = data.results || [];
      this.setData({ assignments, state: assignments.length ? "ready" : "empty" });
    } catch (error) {
      this.setData({ state: "error", errorMessage: error.message || "assignment 加载失败" });
    }
  },

  openAssignment(event) {
    wx.navigateTo({ url: `/pages/consolidation-detail/index?id=${event.currentTarget.dataset.id}` });
  }
});
