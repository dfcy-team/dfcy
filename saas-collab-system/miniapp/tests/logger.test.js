"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { redact } = require("../core/telemetry/logger");

test("logger recursively redacts credentials", () => {
  const result = redact({
    authorization: "Bearer secret",
    nested: {
      password: "plain-text",
      safe: "visible",
      session_key: "server-only"
    },
    rows: [{ token: "abc" }]
  });

  assert.equal(result.authorization, "***");
  assert.equal(result.nested.password, "***");
  assert.equal(result.nested.session_key, "***");
  assert.equal(result.nested.safe, "visible");
  assert.equal(result.rows[0].token, "***");
});

test("logger handles circular data", () => {
  const input = { safe: true };
  input.self = input;
  assert.equal(redact(input).self, "[Circular]");
});
