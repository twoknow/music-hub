from __future__ import annotations

import json
from dataclasses import dataclass

from .config import AppPaths, ensure_dirs


LOUDNORM_FILTER = [{"name": "loudnorm", "enabled": True, "params": {}}]


@dataclass(frozen=True)
class PlaybackPrefs:
    loudnorm_enabled: bool = False


def _prefs_path(paths: AppPaths):
    return paths.base_dir / "settings.json"


def load_playback_prefs(paths: AppPaths) -> PlaybackPrefs:
    ensure_dirs(paths)
    prefs_path = _prefs_path(paths)
    if not prefs_path.exists():
        return PlaybackPrefs()

    try:
        raw = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return PlaybackPrefs()

    return PlaybackPrefs(loudnorm_enabled=bool(raw.get("loudnorm_enabled", False)))


def save_playback_prefs(paths: AppPaths, prefs: PlaybackPrefs) -> None:
    ensure_dirs(paths)
    prefs_path = _prefs_path(paths)
    tmp = prefs_path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"loudnorm_enabled": prefs.loudnorm_enabled}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(prefs_path)


def af_property_value(prefs: PlaybackPrefs):
    if prefs.loudnorm_enabled:
        return [dict(item) for item in LOUDNORM_FILTER]
    return []


def loudnorm_enabled_from_af(value) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").casefold() != "loudnorm":
            continue
        enabled = item.get("enabled", True)
        if isinstance(enabled, str):
            return enabled.casefold() not in {"no", "false", "0", "off"}
        return bool(enabled)
    return False
