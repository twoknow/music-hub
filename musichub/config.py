from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    db_path: Path
    runtime_dir: Path
    logs_dir: Path
    events_jsonl: Path
    daemon_pid_file: Path
    daemon_log_file: Path
    models_dir: Path
    implicit_recs_file: Path
    model_meta_file: Path
    mpv_pipe: str
    mpv_script: Path
    mpv_exe_hint: Path


def _default_base_dir() -> Path:
    override = os.environ.get("MUSICHUB_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (project_root() / "data").resolve()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_paths() -> AppPaths:
    base = _default_base_dir()
    runtime_dir = base / "runtime"
    logs_dir = base / "logs"
    return AppPaths(
        base_dir=base,
        db_path=base / "musichub.sqlite3",
        runtime_dir=runtime_dir,
        logs_dir=logs_dir,
        events_jsonl=logs_dir / "mpv_events.jsonl",
        daemon_pid_file=runtime_dir / "musicd.pid",
        daemon_log_file=logs_dir / "musicd.log",
        models_dir=base / "models",
        implicit_recs_file=(base / "models" / "implicit_recs.json"),
        model_meta_file=(base / "models" / "model_meta.json"),
        mpv_pipe=r"\\.\pipe\musichub-mpv",
        mpv_script=project_root() / "mpv-scripts" / "musichub.lua",
        mpv_exe_hint=(project_root() / "mpv-portable" / "mpv.exe"),
    )


def ensure_dirs(paths: AppPaths) -> None:
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.models_dir.mkdir(parents=True, exist_ok=True)
