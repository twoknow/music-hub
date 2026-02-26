from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from . import db
from .config import AppPaths


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _guess_source_kind(path: str | None) -> str | None:
    if not path:
        return None
    if "music.youtube.com" in path:
        return "ytmusic"
    if "youtube.com" in path or "youtu.be" in path:
        return "youtube"
    if "://" in path:
        return "url"
    return "local"


def _pick_artist(metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("artist", "ARTIST", "Artist", "album_artist", "ALBUMARTIST", "uploader"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_title(payload: dict[str, Any]) -> str | None:
    for key in ("media_title", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in ("title", "TITLE", "Title"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _event_time_iso(payload: dict[str, Any]) -> str:
    raw = payload.get("time")
    if isinstance(raw, str) and raw:
        return raw
    return datetime.now(UTC).isoformat()


def _upsert_track_from_event(conn, payload: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    source_url = payload.get("path") if isinstance(payload.get("path"), str) else None
    source_kind = _guess_source_kind(source_url)
    title = _pick_title(payload)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
    artist = _pick_artist(metadata)
    duration = _safe_float(payload.get("duration"))
    track_id = db.upsert_track_and_source(
        conn,
        title=title,
        artist=artist,
        duration_sec=duration,
        source_kind=source_kind,
        source_url=source_url,
    )
    return track_id, source_url, source_kind


def ingest_mpv_events(paths: AppPaths) -> dict[str, int]:
    if not paths.events_jsonl.exists():
        return {"read": 0, "new": 0, "skipped": 0}

    conn = db.connect(paths.db_path)
    try:
        offset = db.get_ingest_offset(conn, "mpv_jsonl")
        read_count = 0
        new_count = 0
        skipped = 0

        with paths.events_jsonl.open("r", encoding="utf-8") as f:
            f.seek(offset)
            while True:
                line = f.readline()
                if not line:
                    break
                read_count += 1
                line_end_offset = f.tell()
                line_stripped = line.strip()
                if not line_stripped:
                    db.set_ingest_offset(conn, "mpv_jsonl", line_end_offset)
                    continue
                try:
                    payload = json.loads(line_stripped)
                except json.JSONDecodeError:
                    skipped += 1
                    db.set_ingest_offset(conn, "mpv_jsonl", line_end_offset)
                    continue

                if not db.insert_raw_mpv_event(conn, payload, line_stripped):
                    db.set_ingest_offset(conn, "mpv_jsonl", line_end_offset)
                    continue
                new_count += 1

                event_name = str(payload.get("event") or "unknown")
                ts = _event_time_iso(payload)
                session_id = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
                track_id, source_url, source_kind = _upsert_track_from_event(conn, payload)
                playback_time = _safe_float(payload.get("playback_time"))
                duration = _safe_float(payload.get("duration"))

                if event_name == "play_start":
                    db.record_play_event(
                        conn,
                        occurred_at=ts,
                        track_id=track_id,
                        source_url=source_url,
                        source_kind=source_kind,
                        action="play_start",
                        playback_time_sec=playback_time,
                        duration_sec=duration,
                        session_id=session_id,
                    )
                elif event_name == "play_end":
                    reason = str(payload.get("reason") or "")
                    completed = bool(reason == "eof")
                    if duration and playback_time is not None and duration > 0:
                        completed = completed or ((playback_time / duration) >= 0.8)
                    db.record_play_event(
                        conn,
                        occurred_at=ts,
                        track_id=track_id,
                        source_url=source_url,
                        source_kind=source_kind,
                        action="play_end",
                        completed=completed,
                        reason=reason or None,
                        playback_time_sec=playback_time,
                        duration_sec=duration,
                        session_id=session_id,
                    )
                elif event_name in {"good", "bad"}:
                    db.record_feedback_event(
                        conn,
                        occurred_at=ts,
                        track_id=track_id,
                        source_url=source_url,
                        source_kind=source_kind,
                        kind=event_name,
                        session_id=session_id,
                    )
                elif event_name == "next":
                    db.record_play_event(
                        conn,
                        occurred_at=ts,
                        track_id=track_id,
                        source_url=source_url,
                        source_kind=source_kind,
                        action="next",
                        reason=str(payload.get("reason") or "manual_next"),
                        playback_time_sec=playback_time,
                        duration_sec=duration,
                        session_id=session_id,
                    )

                db.set_ingest_offset(conn, "mpv_jsonl", line_end_offset)

        conn.commit()
        return {"read": read_count, "new": new_count, "skipped": skipped}
    finally:
        conn.close()
