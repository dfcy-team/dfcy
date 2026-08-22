"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  createAttachmentUploadSession,
  getAssignment,
  getAssignments,
  idempotencyKey,
  localUploadEnabled,
  submitHandover
} = require("../services/consolidations");

test("miniapp assignment mock is supplier-scoped and exposes no upload success", async () => {
  const data = await getAssignments(null, { useMock: true });
  assert.equal(data.count, 1);
  assert.equal(data.results[0].allocation.state, "allocated");
  assert.equal(localUploadEnabled({ name: "development", useMock: true }), false);
  const disabled = await createAttachmentUploadSession(null, { name: "development", useMock: true }, data.results[0].allocation.id);
  assert.equal(disabled.status, "disabled");
  assert.match(disabled.message, /不会|未启用/);
});

test("assignment service uses miniapp API2 paths, stable write keys and fail-closed mock handover", async () => {
  const requests = [];
  const client = { request(input) { requests.push(input); return Promise.resolve({ id: 1 }); } };
  const config = { name: "test", useMock: false };
  await getAssignments(client, config, { page: 2, page_size: 10 });
  await getAssignment(client, config, 6101);
  await submitHandover(client, config, 6101, { expected_version: 2, release_version: 1, evidence_ids: [9] });
  assert.deepEqual(requests.map((item) => `${item.method} ${item.path}`), [
    "GET /api/miniapp/supply-chain/consolidations/assignments/",
    "GET /api/miniapp/supply-chain/consolidations/assignments/6101/",
    "POST /api/miniapp/supply-chain/consolidations/assignments/6101/actions/submit-handover/"
  ]);
  assert.equal(requests[2].headers["Idempotency-Key"], idempotencyKey("handover", 6101, { expected_version: 2, release_version: 1, evidence_ids: [9] }));
  assert.equal((await submitHandover(null, { name: "development", useMock: true }, 6101, {})).status, "disabled");
});
