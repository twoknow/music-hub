from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import AppPaths, ensure_dirs


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def export_bundle(
    paths: AppPaths,
    *,
    out_file: str | Path,
    include_events: bool = False,
) -> dict[str, Any]:
    ensure_dirs(paths)
    out_path = Path(out_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "format": "musichub-backup-v1",
        "created_at": _now_iso(),
        "includes": [],
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if paths.db_path.exists():
            zf.write(paths.db_path, "musichub.sqlite3")
            manifest["includes"].append("musichub.sqlite3")

        if paths.models_dir.exists():
            for p in sorted(paths.models_dir.rglob("*")):
                if p.is_file():
                    arcname = Path("models") / p.relative_to(paths.models_dir)
                    zf.write(p, str(arcname))
                    manifest["includes"].append(str(arcname))

        if include_events and paths.events_jsonl.exists():
            zf.write(paths.events_jsonl, "logs/mpv_events.jsonl")
            manifest["includes"].append("logs/mpv_events.jsonl")

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "out_file": str(out_path),
        "entries": len(manifest["includes"]),
        "includes": manifest["includes"],
    }


def import_bundle(
    paths: AppPaths,
    *,
    in_file: str | Path,
    mode: str = "replace",
) -> dict[str, Any]:
    ensure_dirs(paths)
    in_path = Path(in_file).expanduser().resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Backup file not found: {in_path}")

    mode = (mode or "replace").strip().lower()
    if mode != "replace":
        raise ValueError("Only --mode replace is currently supported")

    copied: list[str] = []
    tmp = paths.runtime_dir / "_import_tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(in_path, "r") as zf:
            members = [m for m in zf.namelist() if not m.endswith("/")]
            safe_members: list[str] = []
            for m in members:
                if m == "musichub.sqlite3" or m == "manifest.json" or m.startswith("models/") or m == "logs/mpv_events.jsonl":
                    safe_members.append(m)
            for m in safe_members:
                zf.extract(m, path=tmp)

        db_src = tmp / "musichub.sqlite3"
        if db_src.exists():
            shutil.copy2(db_src, paths.db_path)
            copied.append("musichub.sqlite3")

        model_src = tmp / "models"
        if model_src.exists():
            paths.models_dir.mkdir(parents=True, exist_ok=True)
            for old in paths.models_dir.rglob("*"):
                if old.is_file():
                    old.unlink()
            for src in sorted(model_src.rglob("*")):
                if src.is_file():
                    dst = paths.models_dir / src.relative_to(model_src)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied.append(str(Path("models") / src.relative_to(model_src)))

        events_src = tmp / "logs" / "mpv_events.jsonl"
        if events_src.exists():
            paths.logs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(events_src, paths.events_jsonl)
            copied.append("logs/mpv_events.jsonl")
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    return {"ok": True, "in_file": str(in_path), "mode": mode, "copied": copied}


def export_backup(
    paths: AppPaths,
    out_file: str | Path,
    *,
    include_events: bool = False,
) -> dict[str, Any]:
    return export_bundle(paths, out_file=out_file, include_events=include_events)


def import_backup(
    paths: AppPaths,
    in_file: str | Path,
    *,
    mode: str = "replace",
) -> dict[str, Any]:
    return import_bundle(paths, in_file=in_file, mode=mode)
