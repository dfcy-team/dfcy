"use strict";

const { getConsolidationAssignment, getConsolidationAssignments } = require("../mock/consolidations");

function localUploadEnabled(config = {}) {
  return config.name === "development" && config.localUploadEnabled === true;
}

function disabled(message) {
  return { status: "disabled", code: "FEATURE_UNAVAILABLE", message };
}

function idempotencyKey(action, resourceId, payload = {}) {
  const raw = `${action}:${resourceId}:${JSON.stringify(payload, Object.keys(payload).sort())}`;
  let hash = 2166136261;
  for (let index = 0; index < raw.length; index += 1) hash = Math.imul(hash ^ raw.charCodeAt(index), 16777619);
  return `miniapp-sc-flow-${action}-${resourceId}-${(hash >>> 0).toString(16)}`.slice(0, 128);
}

async function getAssignments(client, config, params = {}) {
  if (config.useMock) return getConsolidationAssignments(params);
  return client.request({ method: "GET", path: "/api/miniapp/supply-chain/consolidations/assignments/", data: params });
}

async function getAssignment(client, config, id) {
  if (config.useMock) return getConsolidationAssignment(id);
  return client.request({ method: "GET", path: `/api/miniapp/supply-chain/consolidations/assignments/${id}/` });
}

async function getAttachmentStatus(client, config, attachmentId) {
  if (config.useMock) return disabled("Mock 环境不伪造附件状态；请连接受控 Django API。");
  return client.request({ method: "GET", path: `/api/miniapp/supply-chain/consolidations/attachments/${attachmentId}/status/` });
}

async function createAttachmentUploadSession(client, config, allocationId) {
  if (!localUploadEnabled(config)) return disabled("上传功能未启用：仅 development 且显式 localUploadEnabled 才允许本地 metadata 上传。");
  return client.request({ method: "POST", path: `/api/miniapp/supply-chain/consolidations/assignments/${allocationId}/attachments/upload-sessions/`, headers: { "Idempotency-Key": idempotencyKey("upload-session", allocationId) } });
}

async function finalizeAttachment(client, config, attachmentId, payload) {
  if (!localUploadEnabled(config)) return disabled("上传功能未启用：不会在 Mock 或生产环境伪造上传成功。");
  return client.request({ method: "POST", path: `/api/miniapp/supply-chain/consolidations/attachments/${attachmentId}/actions/finalize/`, data: payload, headers: { "Idempotency-Key": idempotencyKey("finalize", attachmentId, { upload_session_id: payload?.upload_session_id, file_name: payload?.file_name }) } });
}

async function submitHandover(client, config, allocationId, payload) {
  if (config.useMock) return disabled("Mock 环境不伪造交接提交；请连接受控 Django API 并提交已 accepted 证据。");
  return client.request({ method: "POST", path: `/api/miniapp/supply-chain/consolidations/assignments/${allocationId}/actions/submit-handover/`, data: payload, headers: { "Idempotency-Key": idempotencyKey("handover", allocationId, payload) } });
}

module.exports = {
  createAttachmentUploadSession,
  finalizeAttachment,
  getAssignment,
  getAssignments,
  getAttachmentStatus,
  idempotencyKey,
  localUploadEnabled,
  submitHandover
};
