from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import db
from .config import AppPaths
from .models import load_implicit_cache


@dataclass
class RecItem:
    track_id: int
    title: str
    artist: str | None
    score: float
    source_url: str | None
    source_kind: str | None
    reason: str | None = None
    engine: str = "rule"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _diversify_by_artist(candidates: list[RecItem], limit: int) -> list[RecItem]:
    result: list[RecItem] = []
    artist_counts: dict[str, int] = {}
    remaining = list(candidates)
    while remaining and len(result) < limit:
        best_idx = 0
        best_val = None
        for i, item in enumerate(remaining):
            artist_key = (item.artist or "<unknown>").casefold()
            penalty = artist_counts.get(artist_key, 0) * 2.5
            value = item.score - penalty
            if best_val is None or value > best_val:
                best_val = value
                best_idx = i
        picked = remaining.pop(best_idx)
        result.append(picked)
        artist_key = (picked.artist or "<unknown>").casefold()
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
    return result


def _rule_reason(rec: db.Recommendation, top_artists: dict[str, int]) -> str:
    artist = rec.artist or "<unknown>"
    if artist in top_artists and top_artists[artist] > 0:
        return f"你常给 {artist} 红心（{top_artists[artist]} 次）"
    if rec.fb_score > 0 and rec.play_score > 0:
        return "你给过正反馈且常听完整"
    if rec.fb_score > 0:
        return "你给过正反馈"
    if rec.play_score > 0:
        return "你经常听完类似内容"
    if rec.play_score < 0:
        return "探索项（近期有跳过记录，分数较低）"
    return "探索项"


def rule_recommend(conn, *, limit: int = 10, explain: bool = True) -> list[RecItem]:
    raw = db.fetch_recommendations(conn, limit=max(limit * 3, limit))
    recent_ids = set(db.fetch_recent_track_ids(conn, limit=20))
    top_good_artists_rows = db.fetch_top_good_artists(conn, limit=12)
    top_good_artists = {str(r["artist"]): int(r["goods"]) for r in top_good_artists_rows}

    candidates: list[RecItem] = []
    for r in raw:
        score = float(r.score)
        if r.track_id in recent_ids:
            score -= 1.5
        reason = _rule_reason(r, top_good_artists) if explain else None
        candidates.append(
            RecItem(
                track_id=r.track_id,
                title=r.title,
                artist=r.artist,
                score=score,
                source_url=r.source_url,
                source_kind=r.source_kind,
                reason=reason,
                engine="rule",
            )
        )
    return _diversify_by_artist(candidates, limit=limit)


def implicit_recommend(paths: AppPaths, conn, *, limit: int = 10, explain: bool = True) -> list[RecItem]:
    payload = load_implicit_cache(paths)
    if not payload or not isinstance(payload.get("recommendations"), list):
        return []
    raw_recs = payload["recommendations"]
    ids = [int(r["track_id"]) for r in raw_recs if isinstance(r, dict) and "track_id" in r][: max(limit * 4, limit)]
    track_map = db.fetch_track_source_map(conn, ids)

    items: list[RecItem] = []
    for r in raw_recs:
        if not isinstance(r, dict):
            continue
        tid = int(r.get("track_id"))
        if tid not in track_map:
            continue
        t = track_map[tid]
        reason = "基于跨会话共现（implicit）" if explain else None
        items.append(
            RecItem(
                track_id=tid,
                title=str(t.get("title") or tid),
                artist=t.get("artist"),
                score=float(r.get("score") or 0.0),
                source_url=t.get("source_url"),
                source_kind=t.get("source_kind"),
                reason=reason,
                engine="implicit",
            )
        )
        if len(items) >= max(limit * 3, limit):
            break
    return _diversify_by_artist(items, limit=limit)


def recommend(paths: AppPaths, conn, *, engine: str = "auto", limit: int = 10, explain: bool = True) -> list[RecItem]:
    engine = (engine or "auto").lower()
    if engine not in {"auto", "rule", "implicit"}:
        engine = "auto"

    if engine in {"auto", "implicit"}:
        implicit_items = implicit_recommend(paths, conn, limit=limit, explain=explain)
        if implicit_items:
            return implicit_items
        if engine == "implicit":
            return []
    return rule_recommend(conn, limit=limit, explain=explain)

