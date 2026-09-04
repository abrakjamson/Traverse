import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(
  readFileSync(join(pluginRoot, "plugin.json"), "utf8"),
);
const version = manifest.version;
const releaseBase =
  `https://github.com/abrakjamson/PurePath/releases/download/v${version}`;

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

function releaseAsset() {
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

async function fetchBytes(url, description) {
  let response;
  try {
    response = await fetch(url, {
      headers: {
        "User-Agent": `PurePath-Copilot-Plugin/${version}`,
      },
      redirect: "follow",
    });
  } catch (error) {
    fail(`could not download ${description}.`, error.message);
  }
  if (!response.ok) {
    fail(
      `could not download ${description}.`,
      `HTTP ${response.status} from ${url}`,
    );
  }
  return Buffer.from(await response.arrayBuffer());
}

function parseChecksum(contents, asset) {
  for (const line of contents.toString("utf8").split(/\r?\n/)) {
    const match = line.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (match && match[2] === asset) {
      return match[1].toLowerCase();
    }
  }
  fail(`release checksum for ${asset} is missing or malformed.`);
}

async function installExecutable(executable, digestFile, asset) {
  const sums = await fetchBytes(`${releaseBase}/SHA256SUMS`, "release checksums");
  const expectedDigest = parseChecksum(sums, asset);
  const bytes = await fetchBytes(`${releaseBase}/${asset}`, asset);
  const downloadedDigest = createHash("sha256").update(bytes).digest("hex");
  if (downloadedDigest !== expectedDigest) {
    fail(
      `checksum verification failed for ${asset}.`,
      `expected ${expectedDigest}, received ${downloadedDigest}`,
    );
  }

  const temporary = `${executable}.${process.pid}.tmp`;
  writeFileSync(temporary, bytes, { mode: 0o755 });
  if (process.platform !== "win32") {
    chmodSync(temporary, 0o755);
  }
  try {
    renameSync(temporary, executable);
  } catch (error) {
    if (!existsSync(executable) || sha256(executable) !== expectedDigest) {
      rmSync(temporary, { force: true });
      fail(`could not install ${asset}.`, error.message);
    }
    rmSync(temporary, { force: true });
  }
  writeFileSync(digestFile, `${expectedDigest}\n`);
}

const pluginData =
  process.env.COPILOT_PLUGIN_DATA ??
  process.env.PUREPATH_PLUGIN_DATA ??
  defaultPluginData();
const binaryDirectory = join(pluginData, "bin", `v${version}`);
mkdirSync(binaryDirectory, { recursive: true });

const asset = releaseAsset();
const executableOverride = process.env.PUREPATH_PLUGIN_EXECUTABLE;
const executable = executableOverride ?? join(binaryDirectory, asset);
const digestFile = `${executable}.sha256`;

if (executableOverride) {
  if (!existsSync(executable)) {
    fail(
      "PUREPATH_PLUGIN_EXECUTABLE does not exist.",
      executable,
    );
  }
} else {
  const expectedDigest = existsSync(digestFile)
    ? readFileSync(digestFile, "utf8").trim().toLowerCase()
    : "";
  const cached =
    /^[0-9a-f]{64}$/.test(expectedDigest) &&
    existsSync(executable) &&
    sha256(executable) === expectedDigest;
  if (!cached) {
    await installExecutable(executable, digestFile, asset);
  }
}

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
