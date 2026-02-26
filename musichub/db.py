from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import AppPaths


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(paths: AppPaths) -> None:
    conn = connect(paths.db_path)
    try:
        schema = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().strip().split())


def canonical_key(title: str | None, artist: str | None) -> str:
    t = normalize_text(title) or "unknown-title"
    a = normalize_text(artist) or "unknown-artist"
    return f"{t}::{a}"


def upsert_track_and_source(
    conn: sqlite3.Connection,
    *,
    title: str | None,
    artist: str | None,
    duration_sec: float | None,
    source_kind: str | None,
    source_url: str | None,
    source_id: str | None = None,
) -> int | None:
    if not (title or source_url):
        return None

    title_value = title or source_url or "unknown"
    ckey = canonical_key(title_value, artist)
    conn.execute(
        """
        INSERT INTO tracks(canonical_key, title, artist, duration_sec)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(canonical_key) DO UPDATE SET
            title=excluded.title,
            artist=COALESCE(excluded.artist, tracks.artist),
            duration_sec=COALESCE(excluded.duration_sec, tracks.duration_sec),
            updated_at=CURRENT_TIMESTAMP
        """,
        (ckey, title_value, artist, duration_sec),
    )
    track_id = conn.execute("SELECT id FROM tracks WHERE canonical_key = ?", (ckey,)).fetchone()["id"]

    if source_kind and source_url:
        conn.execute(
            """
            INSERT INTO track_sources(track_id, source_kind, source_id, source_url, source_title, source_artist)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, source_url) DO UPDATE SET
                track_id=excluded.track_id,
                source_id=COALESCE(excluded.source_id, track_sources.source_id),
                source_title=COALESCE(excluded.source_title, track_sources.source_title),
                source_artist=COALESCE(excluded.source_artist, track_sources.source_artist)
            """,
            (track_id, source_kind, source_id, source_url, title_value, artist),
        )
    return int(track_id)


def insert_raw_mpv_event(conn: sqlite3.Connection, payload: dict[str, Any], raw_line: str) -> bool:
    event_hash = sha256(raw_line.rstrip("\r\n").encode("utf-8")).hexdigest()
    try:
        conn.execute(
            "INSERT INTO raw_mpv_events(event_hash, event_name, payload_json) VALUES (?, ?, ?)",
            (
                event_hash,
                str(payload.get("event") or "unknown"),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def record_play_event(
    conn: sqlite3.Connection,
    *,
    occurred_at: str,
    track_id: int | None,
    source_url: str | None,
    source_kind: str | None,
    action: str,
    completed: bool = False,
    reason: str | None = None,
    playback_time_sec: float | None = None,
    duration_sec: float | None = None,
    session_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO play_events(
            occurred_at, track_id, source_url, source_kind, action, completed, reason,
            playback_time_sec, duration_sec, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurred_at,
            track_id,
            source_url,
            source_kind,
            action,
            1 if completed else 0,
            reason,
            playback_time_sec,
            duration_sec,
            session_id,
        ),
    )


def record_feedback_event(
    conn: sqlite3.Connection,
    *,
    occurred_at: str,
    track_id: int | None,
    source_url: str | None,
    source_kind: str | None,
    kind: str,
    weight: float = 1.0,
    session_id: str | None = None,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO feedback_events(
            occurred_at, track_id, source_url, source_kind, kind, weight, session_id, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (occurred_at, track_id, source_url, source_kind, kind, weight, session_id, note),
    )


def get_ingest_offset(conn: sqlite3.Connection, source_name: str) -> int:
    row = conn.execute(
        "SELECT offset_bytes FROM ingest_state WHERE source_name = ?",
        (source_name,),
    ).fetchone()
    return int(row["offset_bytes"]) if row else 0


def set_ingest_offset(conn: sqlite3.Connection, source_name: str, offset_bytes: int) -> None:
    conn.execute(
        """
        INSERT INTO ingest_state(source_name, offset_bytes)
        VALUES (?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            offset_bytes=excluded.offset_bytes,
            updated_at=CURRENT_TIMESTAMP
        """,
        (source_name, int(offset_bytes)),
    )


@dataclass
class Recommendation:
    track_id: int
    title: str
    artist: str | None
    score: float
    source_url: str | None
    source_kind: str | None
    fb_score: float = 0.0
    play_score: float = 0.0


def fetch_recommendations(conn: sqlite3.Connection, limit: int = 10) -> list[Recommendation]:
    rows = conn.execute(
        """
        WITH f_agg AS (
            SELECT
                track_id,
                SUM(CASE
                    WHEN kind = 'good' THEN 6.0 * weight
                    WHEN kind = 'bad' THEN -8.0 * weight
                    ELSE 0 END) AS fb_score,
                MAX(occurred_at) AS last_feedback_at
            FROM feedback_events
            GROUP BY track_id
        ),
        p_agg AS (
            SELECT
                track_id,
                SUM(CASE
                    WHEN action = 'play_end' AND completed = 1 THEN 1.5
                    WHEN action = 'next' THEN -2.0
                    ELSE 0 END) AS play_score,
                MAX(occurred_at) AS last_play_at
            FROM play_events
            GROUP BY track_id
        ),
        agg AS (
            SELECT
                t.id AS track_id,
                t.title,
                t.artist,
                COALESCE(f.fb_score, 0) AS fb_score,
                COALESCE(p.play_score, 0) AS play_score,
                COALESCE(f.last_feedback_at, p.last_play_at, t.updated_at) AS last_seen
            FROM tracks t
            LEFT JOIN f_agg f ON f.track_id = t.id
            LEFT JOIN p_agg p ON p.track_id = t.id
        ),
        preferred_source AS (
            SELECT ts.track_id, ts.source_url, ts.source_kind
            FROM track_sources ts
            INNER JOIN (
                SELECT track_id, MIN(id) AS min_id
                FROM track_sources
                WHERE source_url IS NOT NULL
                GROUP BY track_id
            ) x ON x.track_id = ts.track_id AND x.min_id = ts.id
        )
        SELECT
            a.track_id, a.title, a.artist,
            (a.fb_score + a.play_score) AS score,
            a.fb_score, a.play_score,
            ps.source_url, ps.source_kind
        FROM agg a
        LEFT JOIN preferred_source ps ON ps.track_id = a.track_id
        ORDER BY score DESC, a.last_seen DESC, a.track_id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [
        Recommendation(
            track_id=int(r["track_id"]),
            title=str(r["title"]),
            artist=r["artist"],
            score=float(r["score"]),
            source_url=r["source_url"],
            source_kind=r["source_kind"],
            fb_score=float(r["fb_score"]),
            play_score=float(r["play_score"]),
        )
        for r in rows
    ]


def stats_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM tracks) AS tracks,
            (SELECT COUNT(*) FROM track_sources) AS sources,
            (SELECT COUNT(*) FROM play_events) AS play_events,
            (SELECT COUNT(*) FROM feedback_events) AS feedback_events,
            (SELECT COUNT(*) FROM feedback_events WHERE kind='good') AS good_events,
            (SELECT COUNT(*) FROM feedback_events WHERE kind='bad') AS bad_events
        """
    ).fetchone()
    top_artists = conn.execute(
        """
        WITH fg AS (
            SELECT track_id, SUM(CASE WHEN kind='good' THEN 1 ELSE 0 END) AS goods
            FROM feedback_events
            GROUP BY track_id
        ),
        pg AS (
            SELECT track_id, SUM(CASE WHEN completed=1 THEN 1 ELSE 0 END) AS completes
            FROM play_events
            GROUP BY track_id
        )
        SELECT
            COALESCE(t.artist, '<unknown>') AS artist,
            SUM(COALESCE(fg.goods, 0)) AS goods,
            SUM(COALESCE(pg.completes, 0)) AS completes
        FROM tracks t
        LEFT JOIN fg ON fg.track_id = t.id
        LEFT JOIN pg ON pg.track_id = t.id
        GROUP BY COALESCE(t.artist, '<unknown>')
        ORDER BY goods DESC, completes DESC, artist ASC
        LIMIT 8
        """
    ).fetchall()
    return {
        "tracks": int(counts["tracks"]),
        "sources": int(counts["sources"]),
        "play_events": int(counts["play_events"]),
        "feedback_events": int(counts["feedback_events"]),
        "good_events": int(counts["good_events"]),
        "bad_events": int(counts["bad_events"]),
        "top_artists": [dict(r) for r in top_artists],
    }


def fetch_top_good_artists(conn: sqlite3.Connection, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(t.artist, '<unknown>') AS artist,
            COUNT(*) AS goods
        FROM feedback_events f
        JOIN tracks t ON t.id = f.track_id
        WHERE f.kind = 'good'
        GROUP BY COALESCE(t.artist, '<unknown>')
        ORDER BY goods DESC, artist ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_recent_track_ids(conn: sqlite3.Connection, limit: int = 30) -> list[int]:
    rows = conn.execute(
        """
        SELECT track_id
        FROM (
            SELECT track_id, occurred_at
            FROM play_events
            WHERE track_id IS NOT NULL
            UNION ALL
            SELECT track_id, occurred_at
            FROM feedback_events
            WHERE track_id IS NOT NULL
        )
        GROUP BY track_id
        ORDER BY MAX(occurred_at) DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [int(r["track_id"]) for r in rows if r["track_id"] is not None]


def fetch_track_source_map(conn: sqlite3.Connection, track_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not track_ids:
        return {}
    placeholders = ",".join("?" for _ in track_ids)
    rows = conn.execute(
        f"""
        WITH preferred_source AS (
            SELECT ts.track_id, ts.source_url, ts.source_kind
            FROM track_sources ts
            INNER JOIN (
                SELECT track_id, MIN(id) AS min_id
                FROM track_sources
                WHERE source_url IS NOT NULL
                GROUP BY track_id
            ) x ON x.track_id = ts.track_id AND x.min_id = ts.id
        )
        SELECT t.id AS track_id, t.title, t.artist, t.duration_sec, ps.source_url, ps.source_kind
        FROM tracks t
        LEFT JOIN preferred_source ps ON ps.track_id = t.id
        WHERE t.id IN ({placeholders})
        """,
        tuple(track_ids),
    ).fetchall()
    return {int(r["track_id"]): dict(r) for r in rows}


def fetch_user_profile_weights(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH pos_fb AS (
            SELECT track_id, SUM(CASE WHEN kind='good' THEN 4.0 WHEN kind='bad' THEN -5.0 ELSE 0 END) AS s
            FROM feedback_events
            WHERE track_id IS NOT NULL
            GROUP BY track_id
        ),
        pos_play AS (
            SELECT track_id, SUM(CASE WHEN action='play_end' AND completed=1 THEN 1.0 WHEN action='next' THEN -1.5 ELSE 0 END) AS s
            FROM play_events
            WHERE track_id IS NOT NULL
            GROUP BY track_id
        )
        SELECT
            t.id AS track_id,
            COALESCE(f.s,0)+COALESCE(p.s,0) AS weight
        FROM tracks t
        LEFT JOIN pos_fb f ON f.track_id=t.id
        LEFT JOIN pos_play p ON p.track_id=t.id
        WHERE (COALESCE(f.s,0)+COALESCE(p.s,0)) != 0
        ORDER BY weight DESC, t.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_context_interactions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH e AS (
            SELECT
                COALESCE(NULLIF(session_id, ''), 'd:' || substr(occurred_at,1,10)) AS context_key,
                track_id,
                SUM(CASE
                    WHEN kind='good' THEN 3.0
                    WHEN kind='bad' THEN -4.0
                    ELSE 0 END) AS w
            FROM feedback_events
            WHERE track_id IS NOT NULL
            GROUP BY 1,2
            UNION ALL
            SELECT
                COALESCE(NULLIF(session_id, ''), 'd:' || substr(occurred_at,1,10)) AS context_key,
                track_id,
                SUM(CASE
                    WHEN action='play_end' AND completed=1 THEN 1.0
                    WHEN action='next' THEN -1.0
                    ELSE 0 END) AS w
            FROM play_events
            WHERE track_id IS NOT NULL
            GROUP BY 1,2
        )
        SELECT context_key, track_id, SUM(w) AS weight
        FROM e
        GROUP BY context_key, track_id
        HAVING SUM(w) != 0
        ORDER BY context_key, track_id
        """
    ).fetchall()
    return [dict(r) for r in rows]
