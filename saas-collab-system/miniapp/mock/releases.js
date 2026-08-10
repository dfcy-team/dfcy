"use strict";

const contracts = [
  {
    id: 1001,
    contract_no: "RC-DEMO-1001",
    application_code: "saas-miniapp",
    environment: "test",
    commit_sha: "a1b2c3d4e5f67890",
    api_contract_version: "miniapp-v1",
    scope: ["pages/home", "pages/releases"],
    risk_level: "medium",
    rollback_version: "0.0.9",
    rollback_point: "artifact:stable-009",
    stop_conditions: [
      {
        metric: "login_error_rate",
        operator: ">",
        threshold: 0.05
      }
    ],
    observation_minutes: 30,
    status: "review_pending",
    scheduled_at: null,
    completed_at: null,
    version: 8,
    gate_summary: {
      passed: true,
      required: 6,
      passed_count: 6,
      blockers: []
    },
    gate_results: [
      {
        code: "engineering-quality",
        category: "quality",
        status: "passed",
        evidence_ref: "demo:evidence:engineering-quality"
      },
      {
        code: "miniapp-special",
        category: "quality",
        status: "passed",
        evidence_ref: "demo:evidence:miniapp-special"
      }
    ],
    approvals: [
      {
        approval_type: "business",
        decision: "approved",
        reason: "Demo business approval."
      }
    ],
    artifact: null,
    updated_at: "2026-07-24T08:00:00Z"
  },
  {
    id: 1002,
    contract_no: "RC-DEMO-1002",
    application_code: "saas-miniapp",
    environment: "preview",
    commit_sha: "b1c2d3e4f5a67890",
    risk_level: "low",
    status: "observing",
    scheduled_at: "2026-07-24T09:00:00Z",
    version: 15,
    gate_summary: {
      passed: true,
      required: 6,
      passed_count: 6,
      blockers: []
    },
    updated_at: "2026-07-24T09:20:00Z"
  }
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function getMockReleaseWorkbench() {
  return {
    read_only: true,
    total: contracts.length,
    status_counts: {
      observing: 1,
      review_pending: 1
    },
    recent: clone(contracts)
  };
}

function getMockReleaseContract(id) {
  const contract = contracts.find((item) => String(item.id) === String(id));
  if (!contract) {
    const error = new Error("发布合同不存在");
    error.code = "NOT_FOUND";
    throw error;
  }
  return {
    read_only: true,
    contract: clone(contract)
  };
}

module.exports = {
  getMockReleaseContract,
  getMockReleaseWorkbench
};
