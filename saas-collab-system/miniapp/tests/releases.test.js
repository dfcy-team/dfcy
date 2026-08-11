"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  getReleaseContract,
  getReleaseWorkbench
} = require("../services/releases");

test("mock release workbench is explicitly read-only", async () => {
  const data = await getReleaseWorkbench(null, { useMock: true });
  assert.equal(data.read_only, true);
  assert.equal(data.total, 2);
  assert.ok(data.recent.every((contract) => contract.contract_no));
});

test("mock release detail exposes gates without mutation methods", async () => {
  const data = await getReleaseContract(null, { useMock: true }, 1001);
  assert.equal(data.read_only, true);
  assert.equal(data.contract.gate_summary.passed, true);
  assert.equal(typeof require("../services/releases").approveRelease, "undefined");
  assert.equal(typeof require("../services/releases").executeRelease, "undefined");
});
