from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DATA = Path(
    os.environ.get(
        "COPILOT_PLUGIN_DATA",
        Path.home() / ".cache" / "purepath-plugin",
    )
)
VENV_DIR = PLUGIN_DATA / "venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MARKER_PATH = VENV_DIR / ".purepath-pyproject.sha256"
LOCK_PATH = PLUGIN_DATA / "bootstrap.lock"
SHUTDOWN_PATH = (
    Path(value)
    if (value := os.environ.get("PUREPATH_PLUGIN_SHUTDOWN_FILE"))
    else None
)

active_process: subprocess.Popen[bytes] | None = None


def fail(message: str, detail: str = "") -> None:
    print(f"PurePath plugin: {message}", file=sys.stderr)
    if detail:
        print(detail.strip(), file=sys.stderr)
    raise SystemExit(1)


def stop_active_process(signum: int, _frame: object) -> None:
    if active_process is not None and active_process.poll() is None:
        active_process.terminate()
        try:
            active_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            active_process.kill()
            active_process.wait()
    raise SystemExit(128 + signum)


def shutdown_requested() -> bool:
    return SHUTDOWN_PATH is not None and SHUTDOWN_PATH.exists()


def stop_for_shutdown() -> None:
    global active_process
    if active_process is not None and active_process.poll() is None:
        active_process.terminate()
        try:
            active_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            active_process.kill()
            active_process.wait()
    active_process = None
    raise SystemExit(143)


def run_setup(args: list[str], description: str) -> None:
    global active_process
    active_process = subprocess.Popen(
        args,
        cwd=PLUGIN_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    while True:
        try:
            _, stderr = active_process.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if shutdown_requested():
                stop_for_shutdown()
    return_code = active_process.returncode
    active_process = None
    if return_code != 0:
        fail(description, stderr.decode(errors="replace"))


def acquire_lock(lock_file: object) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        while True:
            if shutdown_requested():
                stop_for_shutdown()
            try:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.25)
    else:
        import fcntl

        while True:
            if shutdown_requested():
                stop_for_shutdown()
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                time.sleep(0.25)


def release_lock(lock_file: object) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def probe(args: list[str], *, env: dict[str, str] | None = None) -> bool:
    try:
        return (
            subprocess.run(
                args,
                cwd=PLUGIN_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            ).returncode
            == 0
        )
    except subprocess.TimeoutExpired:
        return False


def prepare_environment() -> None:
    interpreter_ok = VENV_PYTHON.exists() and probe(
        [str(VENV_PYTHON), "-c", "import sys"]
    )
    if not interpreter_ok:
        run_setup(
            [
                sys.executable,
                "-m",
                "venv",
                "--clear",
                str(VENV_DIR),
            ],
            "could not create the isolated Python environment.",
        )

    pyproject_digest = hashlib.sha256(
        (PLUGIN_ROOT / "pyproject.toml").read_bytes()
    ).hexdigest()
    installed_digest = (
        MARKER_PATH.read_text(encoding="utf-8").strip()
        if MARKER_PATH.exists()
        else ""
    )
    probe_env = dict(os.environ)
    probe_env["PYTHONPATH"] = str(PLUGIN_ROOT / "src")
    dependencies_ok = probe(
        [
            str(VENV_PYTHON),
            "-c",
            "import lxml, mcp, pypdf, wiki_agent",
        ],
        env=probe_env,
    )

    if installed_digest != pyproject_digest or not dependencies_ok:
        run_setup(
            [
                str(VENV_PYTHON),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--quiet",
                "--editable",
                str(PLUGIN_ROOT),
            ],
            "could not install the bundled server and its dependencies.",
        )
        MARKER_PATH.write_text(f"{pyproject_digest}\n", encoding="utf-8")


def main() -> None:
    PLUGIN_DATA.mkdir(parents=True, exist_ok=True)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_active_process)

    with LOCK_PATH.open("a+b") as lock_file:
        acquire_lock(lock_file)
        try:
            prepare_environment()
        finally:
            release_lock(lock_file)

    if shutdown_requested():
        stop_for_shutdown()

    env = dict(os.environ)
    env.setdefault("PUREPATH_CACHE_PATH", str(PLUGIN_DATA / "purepath-cache.sqlite3"))
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(PLUGIN_ROOT / "src"), existing_pythonpath)
        if part
    )
    global active_process
    active_process = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "wiki_agent"],
        cwd=PLUGIN_ROOT,
        env=env,
    )
    while True:
        try:
            return_code = active_process.wait(timeout=0.25)
            active_process = None
            raise SystemExit(return_code)
        except subprocess.TimeoutExpired:
            if shutdown_requested():
                stop_for_shutdown()


if __name__ == "__main__":
    main()
