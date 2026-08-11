"use strict";

const assignments = [
  {
    allocation: {
      id: 6101,
      box_id: 7101,
      box_no: "BX-LOCAL-001",
      quantity: 24,
      state: "allocated",
      version: 2,
      evidence_ids: []
    },
    consolidation: {
      id: 6201,
      consolidation_no: "LC-LOCAL-001",
      region_code: "CN-SOUTH",
      status: "released",
      version: 3,
      collection_cutoff_at: "2026-08-12T09:00:00Z",
      expected_dispatch_at: "2026-08-13T09:00:00Z",
      site: {
        site_code: "SC-LOCAL-SOUTH",
        name: "华南本地集货站",
        country_code: "CN",
        province_state: "广东",
        city: "深圳",
        address_line: "本地开发地址（不发运）",
        contact_name: "本地操作员",
        contact_phone: "仅用于本地 Mock",
        delivery_instructions: "请按后端 assignment 指引交接"
      }
    }
  }
];

const clone = (value) => JSON.parse(JSON.stringify(value));

function getConsolidationAssignments(params = {}) {
  const page = Math.max(1, Number(params.page || 1));
  const pageSize = Math.min(100, Math.max(1, Number(params.page_size || 20)));
  const start = (page - 1) * pageSize;
  return { count: assignments.length, next: null, previous: null, results: clone(assignments.slice(start, start + pageSize)) };
}

function getConsolidationAssignment(id) {
  const item = assignments.find((row) => String(row.allocation.id) === String(id));
  if (!item) throw new Error("集货 assignment 不存在");
  return clone(item);
}

function resetMockConsolidations() {
  assignments[0].allocation.state = "allocated";
  assignments[0].allocation.version = 2;
  assignments[0].allocation.evidence_ids = [];
}

module.exports = { getConsolidationAssignment, getConsolidationAssignments, resetMockConsolidations };
