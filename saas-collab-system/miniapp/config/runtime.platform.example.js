"use strict";

// Copy these values into config/runtime.js only for a controlled local
// code2Session integration run. The AppSecret belongs to the backend and must
// never be added here.
module.exports = Object.freeze({
  environment: "development",
  apiBaseUrl: "http://127.0.0.1:8000",
  useMock: false,
  authMode: "platform"
});
