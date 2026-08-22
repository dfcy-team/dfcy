"use strict";

const {
  createAttachmentUploadSession,
  finalizeAttachment,
  getAssignment,
  localUploadEnabled,
  submitHandover
} = require("../../services/consolidations");

function chooseMedia() {
  return new Promise((resolve, reject) => {
    const done = (result) => result?.tempFiles?.length ? resolve(result.tempFiles[0]) : reject(new Error("未选择图片"));
    const fail = () => reject(new Error("相机/相册权限被拒绝，请在系统设置中允许后重试"));
    if (typeof wx.chooseMedia === "function") wx.chooseMedia({ count: 1, mediaType: ["image"], sourceType: ["camera", "album"], success: done, fail });
    else wx.chooseImage({ count: 1, sourceType: ["camera", "album"], success: (result) => done({ tempFiles: result.tempFiles || [{ path: result.tempFilePaths?.[0], size: 0 }] }), fail });
  });
}

function readBase64(path) {
  return new Promise((resolve, reject) => wx.getFileSystemManager().readFile({ filePath: path, encoding: "base64", success: (result) => resolve(result.data), fail: reject }));
}

Page({
  data: { assignment: null, errorMessage: "", localUploadEnabled: false, state: "loading", uploading: false, submitting: false },

  onLoad(options) { this.allocationId = options.id; },
  onShow() { return this.loadAssignment(); },
  onPullDownRefresh() { return this.loadAssignment().finally(() => wx.stopPullDownRefresh()); },

  async loadAssignment() {
    this.setData({ state: "loading", errorMessage: "" });
    const { client, config } = getApp().globalData.services;
    this.setData({ localUploadEnabled: localUploadEnabled(config) });
    try {
      const assignment = await getAssignment(client, config, this.allocationId);
      this.setData({ assignment, state: "ready" });
    } catch (error) {
      this.setData({ state: "error", errorMessage: error.message || "assignment 加载失败" });
    }
  },

  async chooseEvidence() {
    if (!this.data.localUploadEnabled) return wx.showModal({ title: "功能未启用", content: "附件上传仅在 development 且显式 localUploadEnabled 开关下可用；不会伪造生产上传成功。", showCancel: false });
    if (this.data.uploading) return;
    this.setData({ uploading: true });
    try {
      const file = await chooseMedia();
      const fileName = String(file.path || "").split("/").pop() || "evidence.jpg";
      if (!/\.(jpe?g|png)$/i.test(fileName)) throw new Error("仅支持 JPEG/PNG；HEIC 请先在系统相册转换后再选取");
      if (file.size && file.size > 10 * 1024 * 1024) throw new Error("图片超过 10 MiB 限制，请压缩后重试");
      const { client, config } = getApp().globalData.services;
      const session = await createAttachmentUploadSession(client, config, this.allocationId);
      if (session.status === "disabled") throw new Error(session.message);
      const contentBase64 = await readBase64(file.path);
      const result = await finalizeAttachment(client, config, session.id, { upload_session_id: session.upload_session_id, upload_token: session.upload_token, file_name: fileName, claimed_media_type: /\.png$/i.test(fileName) ? "image/png" : "image/jpeg", content_base64: contentBase64 });
      if (result.status === "disabled") throw new Error(result.message);
      wx.showToast({ title: "本地附件已提交", icon: "success" });
      await this.loadAssignment();
    } catch (error) {
      wx.showModal({ title: "上传未完成", content: error.message || "请检查图片、权限或网络后重试", showCancel: false });
    } finally { this.setData({ uploading: false }); }
  },

  async submitHandover() {
    const evidenceIds = this.data.assignment?.allocation?.evidence_ids || [];
    if (!evidenceIds.length) return wx.showModal({ title: "尚无 accepted 证据", content: "只有后端确认 accepted 的证据才能提交交接。当前不会生成或伪造证据。", showCancel: false });
    if (this.data.submitting) return;
    this.setData({ submitting: true });
    try {
      const { client, config } = getApp().globalData.services;
      const allocation = this.data.assignment.allocation;
      const result = await submitHandover(client, config, allocation.id, { expected_version: allocation.version, release_version: this.data.assignment.consolidation.release_version, evidence_ids: evidenceIds, handover_method: "miniapp", handover_reference: `LOCAL-${allocation.id}` });
      if (result.status === "disabled") throw new Error(result.message);
      wx.showToast({ title: "交接请求已提交", icon: "success" });
      await this.loadAssignment();
    } catch (error) { wx.showModal({ title: "交接未完成", content: error.message || "请刷新后重试", showCancel: false }); }
    finally { this.setData({ submitting: false }); }
  }
});
