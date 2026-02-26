from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db
from .config import AppPaths


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TrainResult:
    engine: str
    ok: bool
    message: str
    recommendations: int = 0
    contexts: int = 0
    items: int = 0
    notes: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "ok": self.ok,
            "message": self.message,
            "recommendations": self.recommendations,
            "contexts": self.contexts,
            "items": self.items,
            "notes": self.notes or [],
        }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def train_implicit_cache(paths: AppPaths, *, topn: int = 200, k: int = 64) -> TrainResult:
    try:
        import numpy as np  # type: ignore
        from scipy.sparse import csr_matrix  # type: ignore
        from implicit.nearest_neighbours import BM25Recommender  # type: ignore
    except Exception as exc:
        return TrainResult(
            engine="implicit",
            ok=False,
            message="implicit stack unavailable",
            notes=[f"{exc}", "Install: pip install implicit scipy numpy"],
        )

    conn = db.connect(paths.db_path)
    try:
        interactions = db.fetch_context_interactions(conn)
        profile = db.fetch_user_profile_weights(conn)
        if not interactions:
            return TrainResult(engine="implicit", ok=False, message="No interactions available for training")

        context_keys = sorted({str(r["context_key"]) for r in interactions})
        track_ids = sorted({int(r["track_id"]) for r in interactions})
        if len(context_keys) < 2 or len(track_ids) < 3:
            return TrainResult(
                engine="implicit",
                ok=False,
                message="Not enough context/item diversity for implicit training",
                contexts=len(context_keys),
                items=len(track_ids),
            )

        ctx_idx = {k: i for i, k in enumerate(context_keys)}
        item_idx = {tid: i for i, tid in enumerate(track_ids)}
        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        for r in interactions:
            w = float(r["weight"])
            if w <= 0:
                continue
            rows.append(ctx_idx[str(r["context_key"])])
            cols.append(item_idx[int(r["track_id"])])
            vals.append(w)
        if not vals:
            return TrainResult(engine="implicit", ok=False, message="No positive interactions for implicit training")

        user_item = csr_matrix((np.array(vals, dtype=np.float32), (np.array(rows), np.array(cols))), shape=(len(context_keys), len(track_ids)))
        if user_item.nnz == 0:
            return TrainResult(engine="implicit", ok=False, message="Empty training matrix")

        model = BM25Recommender(K=int(k))
        model.fit(user_item.T.tocsr())

        profile_map = {int(r["track_id"]): float(r["weight"]) for r in profile}
        pr_rows: list[int] = []
        pr_cols: list[int] = []
        pr_vals: list[float] = []
        for tid, w in profile_map.items():
            if tid in item_idx and w > 0:
                pr_rows.append(0)
                pr_cols.append(item_idx[tid])
                pr_vals.append(float(w))
        if not pr_vals:
            return TrainResult(
                engine="implicit",
                ok=False,
                message="No positive user profile weights overlap with trained items",
                contexts=len(context_keys),
                items=len(track_ids),
            )

        profile_user_item = csr_matrix(
            (np.array(pr_vals, dtype=np.float32), (np.array(pr_rows), np.array(pr_cols))),
            shape=(1, len(track_ids)),
        )

        ids, scores = model.recommend(
            0,
            profile_user_item,
            N=int(topn),
            filter_already_liked_items=True,
            recalculate_user=True,
        )

        recs = []
        for idx, score in zip(ids.tolist(), scores.tolist()):
            tid = track_ids[int(idx)]
            recs.append({"track_id": tid, "score": float(score)})

        payload = {
            "engine": "implicit",
            "created_at": _now_iso(),
            "contexts": len(context_keys),
            "items": len(track_ids),
            "params": {"topn": int(topn), "k": int(k)},
            "recommendations": recs,
        }
        _write_json(paths.implicit_recs_file, payload)

        meta = _load_json(paths.model_meta_file) or {}
        meta["implicit"] = {
            "created_at": payload["created_at"],
            "contexts": payload["contexts"],
            "items": payload["items"],
            "recommendations": len(recs),
            "params": payload["params"],
        }
        _write_json(paths.model_meta_file, meta)

        return TrainResult(
            engine="implicit",
            ok=True,
            message="Implicit recommendation cache trained",
            recommendations=len(recs),
            contexts=len(context_keys),
            items=len(track_ids),
        )
    finally:
        conn.close()


def load_implicit_cache(paths: AppPaths) -> dict[str, Any] | None:
    return _load_json(paths.implicit_recs_file)

