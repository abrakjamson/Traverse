import { spawn, spawnSync } from "node:child_process";
import { existsSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const shutdownFile = join(
  tmpdir(),
  `purepath-plugin-shutdown-${process.pid}`,
);

function fail(message, detail = "") {
  process.stderr.write(`PurePath plugin: ${message}\n`);
  if (detail) {
    process.stderr.write(`${detail.trim()}\n`);
  }
  process.exit(1);
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? [
          { command: "py", prefix: ["-3"] },
          { command: "python", prefix: [] },
          { command: "python3", prefix: [] },
        ]
      : [
          { command: "python3", prefix: [] },
          { command: "python", prefix: [] },
        ];

  for (const candidate of candidates) {
    const probe = spawnSync(
      candidate.command,
      [
        ...candidate.prefix,
        "-c",
        "import sys; raise SystemExit(sys.version_info < (3, 11))",
      ],
      { stdio: "ignore" },
    );
    if (probe.status === 0) {
      return candidate;
    }
  }
  fail("Python 3.11 or newer is required.");
}

const python = findPython();
if (existsSync(shutdownFile)) {
  unlinkSync(shutdownFile);
}
const bootstrap = spawn(
  python.command,
  [
    ...python.prefix,
    join(pluginRoot, "scripts", "run_purepath.py"),
  ],
  {
    cwd: pluginRoot,
    env: {
      ...process.env,
      PUREPATH_PLUGIN_SHUTDOWN_FILE: shutdownFile,
    },
    stdio: "inherit",
  },
);

bootstrap.on("error", (error) => {
  fail("could not start the Python bootstrap process.", error.message);
});

let stopping = false;
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (stopping) {
      return;
    }
    stopping = true;
    writeFileSync(shutdownFile, `${signal}\n`);
    setTimeout(() => {
      if (bootstrap.exitCode === null) {
        bootstrap.kill("SIGKILL");
      }
    }, 10_000).unref();
  });
}

bootstrap.on("exit", (code, signal) => {
  if (existsSync(shutdownFile)) {
    unlinkSync(shutdownFile);
  }
  if (signal) {
    process.exit(signal === "SIGINT" ? 130 : 143);
    return;
  }
  process.exit(code ?? 1);
});
