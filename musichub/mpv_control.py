from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import AppPaths, ensure_dirs


def _resolve_ytdlp(mpv_exe: str) -> str | None:
    """Find yt-dlp: alongside mpv, Python Scripts, or PATH."""
    candidates = [
        Path(mpv_exe).parent / "yt-dlp.exe",
        Path(sys.executable).parent / "yt-dlp.exe",
        Path(sys.executable).parent / "Scripts" / "yt-dlp.exe",
        Path(sys.executable).parents[1] / "Scripts" / "yt-dlp.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    on_path = shutil.which("yt-dlp")
    return on_path


def resolve_mpv_exe(paths: AppPaths) -> str:
    env_override = os.environ.get("MUSICHUB_MPV_EXE")
    if env_override:
        return env_override
    if paths.mpv_exe_hint.exists():
        return str(paths.mpv_exe_hint)
    on_path = shutil.which("mpv")
    if on_path:
        return on_path
    raise FileNotFoundError(
        "mpv not found. Set MUSICHUB_MPV_EXE or install mpv / use portable build."
    )


def launch_mpv(paths: AppPaths, targets: list[str]) -> subprocess.Popen[str]:
    ensure_dirs(paths)
    mpv_exe = resolve_mpv_exe(paths)
    args = [
        mpv_exe,
        "--no-video",
        f"--input-ipc-server={paths.mpv_pipe}",
        f"--script={paths.mpv_script}",
        f"--script-opts=musichub-events_file={paths.events_jsonl}",
        "--ytdl=yes",
    ]
    ytdlp = _resolve_ytdlp(mpv_exe)
    if ytdlp:
        args.append(f"--ytdl-path={ytdlp}")
    args.extend(targets)
    return subprocess.Popen(args)
