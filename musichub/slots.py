from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppPaths

SLOT_PRIMARY = "0"
MAX_SLOTS = 100


@dataclass
class SlotInfo:
    slot_id: str
    pipe: str
    pid: int


def pipe_for_slot(slot_id: str) -> str:
    """Return named pipe path for a given slot ID."""
    if slot_id == SLOT_PRIMARY:
        return r"\\.\pipe\musichub-mpv"
    return rf"\\.\pipe\musichub-mpv-{slot_id}"


def _registry_path(paths: AppPaths) -> Path:
    return Path(paths.runtime_dir) / "mpv_slots.json"


def load_registry(paths: AppPaths) -> dict[str, SlotInfo]:
    p = _registry_path(paths)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: SlotInfo(**v) for k, v in data.items()}
    except json.JSONDecodeError:
        return {}
    except (KeyError, TypeError):
        return {}


def save_registry(paths: AppPaths, registry: dict[str, SlotInfo]) -> None:
    p = _registry_path(paths)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({k: asdict(v) for k, v in registry.items()}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)


def _is_alive(pid: int) -> bool:
    """Check if a PID is alive (Windows + POSIX compatible)."""
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY = 0x00000400
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clean_dead_slots(paths: AppPaths) -> dict[str, SlotInfo]:
    """Remove slots whose PIDs are no longer alive. Returns cleaned registry."""
    registry = load_registry(paths)
    alive = {k: v for k, v in registry.items() if _is_alive(v.pid)}
    if len(alive) != len(registry):
        save_registry(paths, alive)
    return alive


def next_slot_id(registry: dict[str, SlotInfo]) -> str:
    """Find the lowest unused slot ID (as string integer)."""
    for i in range(MAX_SLOTS):
        if str(i) not in registry:
            return str(i)
    raise RuntimeError(f"Too many active mpv slots (max {MAX_SLOTS})")


def register_slot(paths: AppPaths, slot_id: str, pipe: str, pid: int) -> None:
    registry = load_registry(paths)
    registry[slot_id] = SlotInfo(slot_id=slot_id, pipe=pipe, pid=pid)
    save_registry(paths, registry)


def unregister_slot(paths: AppPaths, slot_id: str) -> None:
    registry = load_registry(paths)
    if registry.pop(slot_id, None) is not None:
        save_registry(paths, registry)
