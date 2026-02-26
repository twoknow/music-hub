from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import db
from .config import AppPaths, ensure_dirs, get_paths
from .events_ingest import ingest_mpv_events


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None
    pid_file: Path
    log_file: Path


def _read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in proc.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(paths: AppPaths | None = None) -> DaemonStatus:
    paths = paths or get_paths()
    ensure_dirs(paths)
    pid = _read_pid(paths.daemon_pid_file)
    running = bool(pid and _pid_exists(pid))
    if not running and paths.daemon_pid_file.exists():
        try:
            paths.daemon_pid_file.unlink()
        except OSError:
            pass
        pid = None
    return DaemonStatus(running=running, pid=pid, pid_file=paths.daemon_pid_file, log_file=paths.daemon_log_file)


def run_loop(paths: AppPaths | None = None, *, poll_sec: float = 2.0, once: bool = False) -> int:
    paths = paths or get_paths()
    ensure_dirs(paths)
    db.init_db(paths)
    paths.daemon_pid_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
        with paths.daemon_log_file.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"time": _now_iso(), "event": "daemon_start", "pid": os.getpid()}) + "\n")
            log.flush()
            while True:
                result = ingest_mpv_events(paths)
                if result.get("new", 0):
                    log.write(json.dumps({"time": _now_iso(), "event": "ingest", **result}, ensure_ascii=False) + "\n")
                    log.flush()
                if once:
                    break
                time.sleep(max(0.2, float(poll_sec)))
    finally:
        try:
            if paths.daemon_pid_file.exists() and _read_pid(paths.daemon_pid_file) == os.getpid():
                paths.daemon_pid_file.unlink()
        except OSError:
            pass
    return 0


def start(paths: AppPaths | None = None, *, poll_sec: float = 2.0) -> DaemonStatus:
    paths = paths or get_paths()
    ensure_dirs(paths)
    st = status(paths)
    if st.running:
        return st

    project_root = str(Path(__file__).resolve().parents[1])
    cmd = [sys.executable, "-m", "musichub.cli", "daemon", "run", "--poll-sec", str(poll_sec)]
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = project_root if not existing_pp else f"{project_root}{os.pathsep}{existing_pp}"

    with paths.daemon_log_file.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
            startupinfo=startupinfo,
            close_fds=True,
        )
    time.sleep(0.6)
    return status(paths)


def stop(paths: AppPaths | None = None) -> DaemonStatus:
    paths = paths or get_paths()
    st = status(paths)
    if not st.running or not st.pid:
        return status(paths)

    pid = st.pid
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False)
    else:
        os.kill(pid, signal.SIGTERM)
    time.sleep(0.5)
    return status(paths)
