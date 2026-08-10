"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const requiredFiles = [
  "app.js",
  "app.json",
  "app.wxss",
  "config/index.js",
  "config/runtime.js",
  "core/auth/session.js",
  "core/request/client.js",
  "core/telemetry/logger.js",
  "pages/bootstrap/index.js",
  "pages/login/index.js",
  "pages/home/index.js",
  "pages/status/index.js",
  "project.config.json",
  "sitemap.json"
];

function fail(message) {
  process.stderr.write(`VALIDATION FAILED: ${message}\n`);
  process.exitCode = 1;
}

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" ? [] : walk(target);
    }
    return [target];
  });
}

for (const relativePath of requiredFiles) {
  if (!fs.existsSync(path.join(root, relativePath))) {
    fail(`missing required file: ${relativePath}`);
  }
}

const jsonFiles = walk(root).filter((file) => file.endsWith(".json"));
for (const file of jsonFiles) {
  try {
    JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    fail(`invalid JSON ${path.relative(root, file)}: ${error.message}`);
  }
}

const appConfig = JSON.parse(fs.readFileSync(path.join(root, "app.json"), "utf8"));
for (const page of appConfig.pages || []) {
  for (const extension of [".js", ".json", ".wxml", ".wxss"]) {
    const target = path.join(root, `${page}${extension}`);
    if (!fs.existsSync(target)) {
      fail(`page declaration has no ${extension} file: ${page}`);
    }
  }
}

const sourceFiles = walk(root).filter(
  (file) => file.endsWith(".js") && !file.includes(`${path.sep}tests${path.sep}`)
);
for (const file of sourceFiles) {
  const result = spawnSync(process.execPath, ["--check", file], {
    encoding: "utf8"
  });
  if (result.status !== 0) {
    fail(`JavaScript syntax error in ${path.relative(root, file)}: ${result.stderr}`);
  }

  const source = fs.readFileSync(file, "utf8");
  const relativeRequires = source.matchAll(
    /require\(\s*["'](\.[^"']+)["']\s*\)/g
  );
  for (const match of relativeRequires) {
    const request = match[1];
    const target = path.resolve(path.dirname(file), request);
    if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
      fail(
        `directory require is not supported by the WeChat runtime in ${path.relative(
          root,
          file
        )}: ${request}; reference the index file explicitly`
      );
      continue;
    }
    if (
      !fs.existsSync(target) &&
      !fs.existsSync(`${target}.js`) &&
      !fs.existsSync(`${target}.json`)
    ) {
      fail(
        `unresolved relative require in ${path.relative(root, file)}: ${request}`
      );
    }
  }
}

const forbiddenPaths = ["/api/internal/", "/api/rpa/", "/api/finance/"];
const runtimeSources = sourceFiles
  .filter((file) => !file.endsWith(path.join("scripts", "validate-project.js")))
  .map((file) => fs.readFileSync(file, "utf8"))
  .join("\n");
for (const forbiddenPath of forbiddenPaths) {
  if (runtimeSources.includes(forbiddenPath)) {
    fail(`forbidden API boundary found in miniapp runtime: ${forbiddenPath}`);
  }
}

const projectConfig = JSON.parse(
  fs.readFileSync(path.join(root, "project.config.json"), "utf8")
);
if (projectConfig.appid !== "touristappid") {
  fail("repository project.config.json must not contain a real AppID");
}

if (!process.exitCode) {
  process.stdout.write(
    `Miniapp validation passed: ${appConfig.pages.length} pages, ${sourceFiles.length} JavaScript files.\n`
  );
}
