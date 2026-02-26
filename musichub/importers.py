from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from . import db
from .config import AppPaths


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ImportResult:
    source: str
    tracks_upserted: int = 0
    play_events: int = 0
    feedback_events: int = 0
    skipped: int = 0
    notes: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "tracks_upserted": self.tracks_upserted,
            "play_events": self.play_events,
            "feedback_events": self.feedback_events,
            "skipped": self.skipped,
            "notes": self.notes or [],
        }


def _coerce_items_from_json(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "tracks", "songs", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _extract_title(item: dict[str, Any]) -> str | None:
    for key in ("title", "name", "song", "track", "videoTitle"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_artist(item: dict[str, Any]) -> str | None:
    for key in ("artist", "artists", "author", "uploader"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            parts = [str(x).strip() for x in v if str(x).strip()]
            if parts:
                return ", ".join(parts)
    if isinstance(item.get("artists"), list):
        names: list[str] = []
        for a in item["artists"]:
            if isinstance(a, dict):
                n = a.get("name")
                if isinstance(n, str) and n.strip():
                    names.append(n.strip())
        if names:
            return ", ".join(names)
    return None


def _extract_url(item: dict[str, Any]) -> str | None:
    for key in ("url", "source_url", "videoUrl", "webpage_url", "link"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    video_id = item.get("videoId") or item.get("video_id")
    if isinstance(video_id, str) and video_id.strip():
        return f"https://music.youtube.com/watch?v={video_id.strip()}"
    return None


def _extract_duration_sec(item: dict[str, Any]) -> float | None:
    for key in ("duration_sec", "duration", "lengthSeconds"):
        v = item.get(key)
        try:
            if v is not None:
                return float(v)
        except (TypeError, ValueError):
            pass
    return None


def _extract_time(item: dict[str, Any]) -> str:
    for key in ("time", "occurred_at", "played_at", "timestamp", "addedAt"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return _now_iso()


def _iter_normalized_items(raw_items: Iterable[dict[str, Any]], source_kind: str) -> Iterable[dict[str, Any]]:
    for item in raw_items:
        title = _extract_title(item)
        artist = _extract_artist(item)
        url = _extract_url(item)
        duration = _extract_duration_sec(item)

        liked = bool(item.get("liked") or item.get("isLiked") or item.get("favorite"))
        disliked = bool(item.get("disliked") or item.get("isDisliked") or item.get("banned"))
        play_count = 0
        try:
            play_count = int(item.get("play_count") or item.get("playCount") or 0)
        except (TypeError, ValueError):
            play_count = 0

        yield {
            "title": title,
            "artist": artist,
            "source_url": url,
            "duration_sec": duration,
            "source_kind": source_kind,
            "liked": liked,
            "disliked": disliked,
            "play_count": max(play_count, 0),
            "time": _extract_time(item),
            "raw": item,
        }


def import_normalized_items(conn, *, source_label: str, items: Iterable[dict[str, Any]]) -> ImportResult:
    result = ImportResult(source=source_label, notes=[])
    for item in items:
        if not (item.get("title") or item.get("source_url")):
            result.skipped += 1
            continue
        track_id = db.upsert_track_and_source(
            conn,
            title=item.get("title"),
            artist=item.get("artist"),
            duration_sec=item.get("duration_sec"),
            source_kind=item.get("source_kind"),
            source_url=item.get("source_url"),
        )
        result.tracks_upserted += 1
        ts = str(item.get("time") or _now_iso())
        source_kind = item.get("source_kind")
        source_url = item.get("source_url")

        if item.get("liked"):
            db.record_feedback_event(
                conn,
                occurred_at=ts,
                track_id=track_id,
                source_url=source_url,
                source_kind=source_kind,
                kind="good",
                note=f"import:{source_label}",
            )
            result.feedback_events += 1
        if item.get("disliked"):
            db.record_feedback_event(
                conn,
                occurred_at=ts,
                track_id=track_id,
                source_url=source_url,
                source_kind=source_kind,
                kind="bad",
                note=f"import:{source_label}",
            )
            result.feedback_events += 1

        play_count = int(item.get("play_count") or 0)
        for _ in range(min(play_count, 5)):
            db.record_play_event(
                conn,
                occurred_at=ts,
                track_id=track_id,
                source_url=source_url,
                source_kind=source_kind,
                action="play_end",
                completed=True,
                reason=f"import:{source_label}",
                duration_sec=item.get("duration_sec"),
            )
            result.play_events += 1
    return result


def import_json_file(paths: AppPaths, *, source_kind: str, json_file: str | Path) -> ImportResult:
    p = Path(json_file).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    raw_items = _coerce_items_from_json(data)
    conn = db.connect(paths.db_path)
    try:
        result = import_normalized_items(
            conn,
            source_label=f"{source_kind}-json",
            items=_iter_normalized_items(raw_items, source_kind),
        )
        result.notes = (result.notes or []) + [f"file={p}"]
        conn.commit()
        return result
    finally:
        conn.close()


def import_ytm_live(paths: AppPaths, *, auth_json: str | Path | None = None, include_history: bool = True) -> ImportResult:
    try:
        from ytmusicapi import YTMusic  # type: ignore
    except Exception as exc:
        return ImportResult(
            source="ytm-live",
            skipped=0,
            notes=[f"ytmusicapi unavailable: {exc}", "Install: pip install ytmusicapi"],
        )

    auth = str(Path(auth_json).expanduser().resolve()) if auth_json else None
    if not auth:
        return ImportResult(
            source="ytm-live",
            notes=["Missing auth JSON. Provide --auth-json exported via ytmusicapi browser auth workflow."],
        )

    ytm = YTMusic(auth=auth)
    collected: list[dict[str, Any]] = []
    notes: list[str] = []

    # Liked songs (method names vary slightly across versions; keep defensive)
    try:
        liked = ytm.get_liked_songs(limit=5000)  # type: ignore[arg-type]
        tracks = liked.get("tracks", []) if isinstance(liked, dict) else []
        for t in tracks:
            if not isinstance(t, dict):
                continue
            collected.append(
                {
                    "title": t.get("title"),
                    "artists": [a.get("name") for a in t.get("artists", []) if isinstance(a, dict)],
                    "videoId": t.get("videoId"),
                    "duration_sec": None,
                    "liked": True,
                    "play_count": 0,
                    "time": _now_iso(),
                }
            )
        notes.append(f"liked_tracks={len(tracks)}")
    except Exception as exc:
        notes.append(f"get_liked_songs failed: {exc}")

    if include_history:
        try:
            history = ytm.get_history()  # type: ignore[misc]
            for h in history if isinstance(history, list) else []:
                if not isinstance(h, dict):
                    continue
                collected.append(
                    {
                        "title": h.get("title"),
                        "artists": [a.get("name") for a in h.get("artists", []) if isinstance(a, dict)],
                        "videoId": h.get("videoId"),
                        "play_count": 1,
                        "time": _now_iso(),
                    }
                )
            notes.append(f"history_items={len(history) if isinstance(history, list) else 0}")
        except Exception as exc:
            notes.append(f"get_history failed: {exc}")

    conn = db.connect(paths.db_path)
    try:
        result = import_normalized_items(
            conn,
            source_label="ytm-live",
            items=_iter_normalized_items(collected, "ytmusic"),
        )
        result.notes = (result.notes or []) + notes
        conn.commit()
        return result
    finally:
        conn.close()


def import_ncm_json(paths: AppPaths, *, json_file: str | Path) -> ImportResult:
    return import_json_file(paths, source_kind="netease", json_file=json_file)

