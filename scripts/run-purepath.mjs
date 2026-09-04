import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function fail(message, detail = "") {
  process.stderr.write(`PurePath plugin: ${message}\n`);
  if (detail) {
    process.stderr.write(`${detail.trim()}\n`);
  }
  process.exit(1);
}

function defaultPluginData() {
  if (process.platform === "win32") {
    return join(
      process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"),
      "PurePath",
      "plugin",
    );
  }
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Caches", "PurePath", "plugin");
  }
  return join(
    process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache"),
    "purepath-plugin",
  );
}

function bundledAsset() {
  const key = `${process.platform}-${process.arch}`;
  const assets = {
    "win32-x64": "purepath-windows-x64.exe",
    "linux-x64": "purepath-linux-x64",
    "darwin-x64": "purepath-macos-x64",
    "darwin-arm64": "purepath-macos-arm64",
  };
  const asset = assets[key];
  if (!asset) {
    fail(
      `platform ${process.platform}/${process.arch} is not supported by this release.`,
    );
  }
  return asset;
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function expectedDigest(asset) {
  const checksumPath = join(pluginRoot, "bin", "SHA256SUMS");
  for (const line of readFileSync(checksumPath, "utf8").split(/\r?\n/)) {
    const match = line.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (match && match[2] === asset) {
      return match[1].toLowerCase();
    }
  }
  fail(`bundled checksum for ${asset} is missing or malformed.`);
}

const asset = bundledAsset();
const executable =
  process.env.PUREPATH_PLUGIN_EXECUTABLE ??
  join(pluginRoot, "bin", asset);
if (!existsSync(executable)) {
  fail("the bundled PurePath executable is missing.", executable);
}

if (!process.env.PUREPATH_PLUGIN_EXECUTABLE) {
  const expected = expectedDigest(asset);
  const actual = sha256(executable);
  if (actual !== expected) {
    fail(
      `checksum verification failed for bundled ${asset}.`,
      `expected ${expected}, received ${actual}`,
    );
  }
}

const pluginData =
  process.env.COPILOT_PLUGIN_DATA ??
  process.env.PUREPATH_PLUGIN_DATA ??
  defaultPluginData();
const server = spawn(executable, [], {
  cwd: pluginRoot,
  env: {
    ...process.env,
    PUREPATH_CACHE_PATH:
      process.env.PUREPATH_CACHE_PATH ??
      join(pluginData, "purepath-cache.sqlite3"),
  },
  stdio: "inherit",
});

server.on("error", (error) => {
  fail("could not start the standalone MCP server.", error.message);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.kill(signal);
  });
}

server.on("exit", (code, signal) => {
  if (signal) {
    process.exit(signal === "SIGINT" ? 130 : 143);
    return;
  }
  process.exit(code ?? 1);
});
