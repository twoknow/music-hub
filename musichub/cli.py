import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import db
from .config import AppPaths, ensure_dirs, get_paths
from .daemon import run_loop as daemon_run_loop, start as daemon_start, status as daemon_status, stop as daemon_stop
from .events_ingest import ingest_mpv_events
from .importers import import_json_file, import_ncm_json, import_ytm_live
from .models import train_implicit_cache
from .mpv_control import launch_mpv, resolve_mpv_exe
from .mpv_ipc import MpvIpcClient, MpvIpcError
from .nl import maybe_extract_direct_command, parse_freeform
from .recommender import RecItem, recommend
from .slots import (
    SLOT_PRIMARY,
    active_slot_info,
    clean_dead_slots,
    next_slot_id,
    pid_is_alive,
    pipe_for_slot,
    register_slot,
    unregister_slot,
)


def _pick_artist(meta: dict[str, Any]) -> str | None:
    if isinstance(meta.get("artist"), str):
        return meta["artist"]
    if isinstance(meta.get("uploader"), str):
        return meta["uploader"]
    return None


def _guess_source_kind(url: str | None) -> str:
    if not url:
        return "local"
    if "music.youtube.com" in url:
        return "ytmusic"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    return "url"


def _snapshot_mpv_slot(paths, slot_id: str) -> dict[str, Any]:
    info = active_slot_info(paths, slot_id)
    if not info:
        return {}

    def _optional_property(client: MpvIpcClient, name: str, default: Any = None) -> Any:
        try:
            return client.get_property(name)
        except MpvIpcError:
            return default

    for attempt in range(3):
        client = MpvIpcClient(info.pipe)
        try:
            path = client.get_property("path")
            if path:
                metadata = _optional_property(client, "metadata", {})
                return {
                    "path": path,
                    "media_title": _optional_property(client, "media-title"),
                    "duration": _optional_property(client, "duration"),
                    "time_pos": _optional_property(client, "time-pos"),
                    "chapter": _optional_property(client, "chapter"),
                    "chapter_metadata": _optional_property(client, "chapter-metadata"),
                    "playlist_pos": _optional_property(client, "playlist-pos"),
                    "playlist_count": _optional_property(client, "playlist-count"),
                    "metadata": metadata if isinstance(metadata, dict) else {},
                }
        except Exception:
            time.sleep(0.3)
            continue

    return {}


def _wait_for_pid_exit(pid: int, timeout_sec: float = 2.0) -> bool:
    deadline = time.time() + max(timeout_sec, 0.0)
    while time.time() < deadline:
        if not pid_is_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_is_alive(pid)


def _kill_pid(pid: int) -> bool:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            os.kill(pid, 9)
    except Exception:
        pass
    return _wait_for_pid_exit(pid, timeout_sec=2.0)


def _stop_slot_instance(paths, slot_id: str, info, *, unregister: bool = True) -> bool:
    stopped = False
    try:
        MpvIpcClient(info.pipe).command(["quit"])
        stopped = _wait_for_pid_exit(info.pid, timeout_sec=1.5)
    except MpvIpcError:
        stopped = False

    if not stopped:
        stopped = _kill_pid(info.pid)

    if stopped and unregister:
        unregister_slot(paths, slot_id)
    return stopped


def _wait_for_slot_ipc(pipe: str, timeout_sec: float = 4.0) -> None:
    deadline = time.time() + max(timeout_sec, 0.5)
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = MpvIpcClient(pipe, connect_timeout_sec=0.25).command(["get_property", "playlist-count"], timeout_sec=0.5)
            if resp.get("error") in {None, "success"}:
                return
            last_err = MpvIpcError(f"mpv IPC returned error for {pipe}: {resp}")
        except Exception as exc:
            last_err = exc
        time.sleep(0.1)
    raise MpvIpcError(f"Timed out waiting for slot IPC at {pipe}: {last_err}")


def _launch_registered_slot(paths, targets: list[str], *, slot_id: str = SLOT_PRIMARY):
    proc = launch_mpv(paths, targets, slot_id=slot_id)
    pipe = pipe_for_slot(slot_id, paths)
    try:
        _wait_for_slot_ipc(pipe)
    except Exception as exc:
        _kill_pid(int(proc.pid))
        raise MpvIpcError(f"mpv failed to take slot {slot_id!r}") from exc
    register_slot(paths, slot_id, pipe, int(proc.pid))
    return proc


def _restart_slot_with_targets(paths, slot_id: str, targets: list[str]):
    info = active_slot_info(paths, slot_id)
    if info is not None and not _stop_slot_instance(paths, slot_id, info):
        raise MpvIpcError(f"Unable to stop existing slot {slot_id!r} before restart")
    return _launch_registered_slot(paths, targets, slot_id=slot_id)


def _list_profile_mpv_pids(paths) -> list[int]:
    markers = [str(paths.mpv_pipe).casefold(), str(paths.events_jsonl).casefold()]
    try:
        if os.name == "nt":
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name = 'mpv.exe'\" | "
                    "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            raw = proc.stdout.strip()
            if proc.returncode != 0 or not raw or raw == "null":
                return []
            data = json.loads(raw)
        else:
            proc = subprocess.run(
                ["ps", "-ax", "-o", "pid=,command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode != 0:
                return []
            data = []
            for line in proc.stdout.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) != 2:
                    continue
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                data.append({"ProcessId": pid, "CommandLine": parts[1]})
    except Exception:
        return []

    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    out: list[int] = []
    for row in rows:
        try:
            pid = int(row.get("ProcessId"))
        except (AttributeError, TypeError, ValueError):
            continue
        cmdline = str(row.get("CommandLine") or "").casefold()
        if any(marker and marker in cmdline for marker in markers):
            out.append(pid)
    return sorted(set(out))


def _stop_profile_orphans(paths, known_pids: set[int]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for pid in _list_profile_mpv_pids(paths):
        if pid in known_pids:
            continue
        results.append({"slot": "orphan", "pid": pid, "ok": _kill_pid(pid)})
    return results


def _run_single_provider_search(query: str, prefix: str, suffix: str, limit: int) -> list[str]:
    """Helper to run a single yt-dlp search provider."""
    search_term = f"{query}{suffix}"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ignore-errors",
        "--skip-download",
        "--flat-playlist",
        "--print", "webpage_url",
        f"{prefix}{limit}:{search_term}"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("http")]
    except Exception:
        return []


def _run_yt_dlp_search_urls(query: str, limit: int = 1) -> list[str]:
    if query.startswith("http"):
        return [query]

    # Clean query and detect platform preference
    lower_q = query.lower()
    is_live = any(x in lower_q for x in ["live", "演唱会", "现场", "mv", "full", "concert"])
    
    # Platform preference detection
    bili_keywords = ["哔哩哔哩", "bilibili", "b站", "b站"]
    prefers_bili = any(k in lower_q for k in bili_keywords)
    
    # Clean up the query for the actual search engines
    clean_query = query
    for k in bili_keywords:
        clean_query = clean_query.replace(k, "").replace(k.upper(), "")
    clean_query = clean_query.strip()

    # Define providers with dynamic suffixes
    # Suffix only added for non-live, official-sounding requests
    yt_suffix = " official audio" if not is_live else ""
    
    providers = [
        ("ytsearch", yt_suffix),
        ("bilisearch", ""),
        ("scsearch", ""),
    ]

    # Reorder if Bilibili is preferred
    if prefers_bili:
        # Move bilisearch to the front
        providers = [p for p in providers if p[0] == "bilisearch"] + [p for p in providers if p[0] != "bilisearch"]

    urls: list[str] = []
    seen: set[str] = set()

    # Run searches in parallel
    results_map = {}
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        future_to_provider = {
            executor.submit(_run_single_provider_search, clean_query, p[0], p[1], limit): p[0] 
            for p in providers
        }
        
        for future in as_completed(future_to_provider):
            p_name = future_to_provider[future]
            try:
                results_map[p_name] = future.result()
            except Exception:
                results_map[p_name] = []

    # Interleave results based on provider priority
    for p_name, _ in providers:
        for url in results_map.get(p_name, []):
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= limit:
                    break
        if len(urls) >= limit:
            break

    if not urls:
        # Fallback to a plain youtube search if nothing found
        urls = _run_single_provider_search(query, "ytsearch", "", limit)

    if not urls:
        raise RuntimeError(f"全网搜索未找到结果: {query}")
    return urls


def _get_yt_related_urls(url: str, limit: int = 5) -> list[str]:
    """Fetch related videos for a YouTube URL using yt-dlp."""
    canonical = _canonical_youtube_watch_url(url)
    if not canonical:
        return []

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ignore-errors",
        "--skip-download",
        "--flat-playlist",
        "--print", "webpage_url",
        canonical,
        "--playlist-items", f"2-{limit+1}" # Skip the current video itself
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out: list[str] = []
        seen: set[str] = set()
        for line in proc.stdout.splitlines():
            candidate = line.strip()
            if not candidate.startswith("http"):
                continue
            candidate_canonical = _canonical_youtube_watch_url(candidate)
            if canonical and candidate_canonical == canonical:
                continue
            dedupe_key = candidate_canonical or candidate
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(candidate)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _run_yt_dlp_print_url(query: str) -> str:
    return _run_yt_dlp_search_urls(query, limit=1)[0]


def _extract_youtube_video_id(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.netloc or "").casefold()
    path = parsed.path or ""
    video_id = None

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.strip("/").split("/")[0]
        video_id = candidate or None
    elif host.endswith("youtube.com"):
        if path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
            video_id = candidate
        else:
            parts = [part for part in path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed", "v"}:
                video_id = parts[1]

    if not video_id:
        return None

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return video_id
    return None


def _canonical_youtube_watch_url(url: str | None) -> str | None:
    video_id = _extract_youtube_video_id(url)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def _build_radio_seed_query(title: str | None, artist: str | None) -> str | None:
    title_text = str(title or "").strip()
    artist_text = str(artist or "").strip()
    parts = [part for part in [artist_text, title_text] if part]
    if not parts:
        return None
    return " ".join(parts)


def _radio_search_fallback(query: str | None, *, limit: int, exclude_url: str | None = None) -> list[str]:
    if not query:
        return []

    excluded = _canonical_youtube_watch_url(exclude_url)
    try:
        urls = _run_yt_dlp_search_urls(query, limit=max(limit + 1, limit))
    except Exception:
        return []
    out: list[str] = []
    for url in urls:
        canonical = _canonical_youtube_watch_url(url)
        if excluded and canonical == excluded:
            continue
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def _upsert_from_snapshot(conn, snap: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    source_url = snap.get("path") if isinstance(snap.get("path"), str) else None
    meta = snap.get("metadata") if isinstance(snap.get("metadata"), dict) else {}
    track_id = db.upsert_track_and_source(
        conn,
        title=snap.get("media_title") if isinstance(snap.get("media_title"), str) else None,
        artist=_pick_artist(meta),
        duration_sec=float(snap["duration"]) if isinstance(snap.get("duration"), (int, float)) else None,
        source_kind=_guess_source_kind(source_url),
        source_url=source_url,
    )
    return track_id, source_url, _guess_source_kind(source_url)


def _ensure_ready():
    paths = get_paths()
    ensure_dirs(paths)
    db.init_db(paths)
    return paths


def _safe_sync_events(paths=None) -> dict[str, int]:
    return ingest_mpv_events(paths or get_paths())


def _resolve_slot_pipe(paths, slot: str | None) -> tuple[str, str]:
    target = (slot or SLOT_PRIMARY).strip()
    registry = clean_dead_slots(paths)
    info = registry.get(target)
    if info is not None:
        return target, info.pipe
    active = sorted(registry.keys(), key=lambda x: int(x))
    raise RuntimeError(f"Slot {target!r} not active. Active slots: {active}")


def _get_mpv_snapshot(paths, slot_id: str) -> dict[str, Any]:
    snap = _snapshot_mpv_slot(paths, slot_id)
    if not snap:
        raise MpvIpcError(f"Unable to snapshot slot {slot_id!r}")
    return snap


def _load_targets_into_client(client: MpvIpcClient, targets: list[str]) -> int:
    loaded = 0
    for i, url in enumerate(targets):
        mode = "replace" if i == 0 else "append"
        resp = client.command(["loadfile", url, mode])
        if resp.get("error") not in {None, "success"}:
            raise MpvIpcError(f"mpv loadfile failed: {resp}")
        loaded += 1
    return loaded


def _append_recommendations_to_slot(
    paths,
    slot_id: str,
    *,
    client: MpvIpcClient | None = None,
    limit: int = 3,
) -> int:
    slot_client = client
    if slot_client is None:
        _, pipe = _resolve_slot_pipe(paths, slot_id)
        slot_client = MpvIpcClient(pipe)

    with db.connect(paths.db_path) as conn:
        items = recommend(paths, conn, limit=max(int(limit), 1), explain=False)
    target_urls = [item.source_url for item in items if item.source_url]
    if not target_urls:
        return 0

    for url in target_urls:
        resp = slot_client.command(["loadfile", url, "append"])
        if resp.get("error") not in {None, "success"}:
            raise MpvIpcError(f"mpv append failed: {resp}")
    return len(target_urls)


def _recover_next_playback(paths, slot_id: str) -> tuple[bool, str | None]:
    with db.connect(paths.db_path) as conn:
        items = recommend(paths, conn, limit=1, explain=False)
    target_url = next((item.source_url for item in items if item.source_url), None)
    if not target_url:
        return False, None

    try:
        _restart_slot_with_targets(paths, slot_id, [target_url])
    except MpvIpcError:
        return False, None
    return True, target_url


def _apply_rec_filters(
    items: list[Any],
    *,
    exclude_artists: list[str] | None = None,
    exclude_tracks: list[str] | None = None,
    min_score: float | None = None,
) -> list[Any]:
    artist_terms = [x.casefold().strip() for x in (exclude_artists or []) if x and x.strip()]
    track_terms = [x.casefold().strip() for x in (exclude_tracks or []) if x and x.strip()]
    threshold = float(min_score) if min_score is not None else None
    out: list[Any] = []
    for item in items:
        artist = str(getattr(item, "artist", "") or "").casefold()
        title = str(getattr(item, "title", "") or "").casefold()
        track_id = str(getattr(item, "track_id", "") or "")
        score = float(getattr(item, "score", 0.0))
        if threshold is not None and score < threshold:
            continue
        if artist_terms and any(term in artist for term in artist_terms):
            continue
        if track_terms and any((term in title) or (term == track_id) for term in track_terms):
            continue
        out.append(item)
    return out


def cmd_radio(args: argparse.Namespace) -> int:
    """Infinite playback mode based on related tracks of current or favorite song."""
    paths = _ensure_ready()
    _safe_sync_events(paths)

    snap = _snapshot_mpv_slot(paths, SLOT_PRIMARY)
    current_url = snap.get("path") if snap else None
    seed_query = None
    if snap:
        meta = snap.get("metadata") if isinstance(snap.get("metadata"), dict) else {}
        seed_query = _build_radio_seed_query(
            snap.get("media_title") if isinstance(snap.get("media_title"), str) else None,
            _pick_artist(meta),
        )

    if current_url and not _canonical_youtube_watch_url(current_url):
        print(f"Current track {current_url} is not a playable YouTube video. Finding another seed...")
        current_url = None

    if not current_url or not seed_query:
        with db.connect(paths.db_path) as conn:
            rows = conn.execute("""
                SELECT ts.source_url, t.title, t.artist
                FROM track_sources ts
                JOIN tracks t ON t.id = ts.track_id
                JOIN feedback_events f ON f.track_id = ts.track_id
                WHERE f.kind = 'good' 
                  AND (ts.source_url LIKE '%youtube.com%' OR ts.source_url LIKE '%youtu.be%')
                ORDER BY f.occurred_at DESC, ts.id DESC
            """).fetchall()
            for row in rows:
                row_url = row["source_url"] if isinstance(row["source_url"], str) else None
                if not current_url and _canonical_youtube_watch_url(row_url):
                    current_url = row_url
                if not seed_query:
                    seed_query = _build_radio_seed_query(row["title"], row["artist"])
                if current_url and seed_query:
                    break

            if not current_url or not seed_query:
                recs = recommend(paths, conn, limit=10)
                for r in recs:
                    if not current_url and r.source_url and _canonical_youtube_watch_url(r.source_url):
                        current_url = r.source_url
                    if not seed_query:
                        seed_query = _build_radio_seed_query(r.title, r.artist)
                    if current_url and seed_query:
                        break

    if not current_url and not seed_query:
        print("Radio Error: No valid YouTube seed or searchable history found. Play or like a real song first.")
        return 1

    related: list[str] = []
    if current_url:
        print(f"Radio Mode: Finding tracks related to {current_url}...")
        related = _get_yt_related_urls(current_url, limit=args.limit)

    if not related:
        if seed_query:
            print(f"Radio Fallback: searching from seed '{seed_query}'...")
            related = _radio_search_fallback(seed_query, limit=args.limit, exclude_url=current_url)

    if not related:
        print("Radio Error: No radio candidates found. The seed link may be dead or search returned nothing.")
        return 1

    mode = "replace"
    if snap and active_slot_info(paths, SLOT_PRIMARY) is not None:
        client = MpvIpcClient(pipe_for_slot(SLOT_PRIMARY, paths))
        for url in related:
            resp = client.command(["loadfile", url, "append"])
            if resp.get("error") not in {None, "success"}:
                raise MpvIpcError(f"mpv append failed: {resp}")
        mode = "append"
    else:
        try:
            client = MpvIpcClient(pipe_for_slot(SLOT_PRIMARY, paths))
            _load_targets_into_client(client, related)
        except MpvIpcError:
            _restart_slot_with_targets(paths, SLOT_PRIMARY, related)

    print(json.dumps({"ok": True, "action": "radio", "mode": mode, "targets": related}, ensure_ascii=False))
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    """Record a personal note/thought for the current track at the current timestamp."""
    paths = _ensure_ready()
    slot_id, pipe = _resolve_slot_pipe(paths, args.slot)
    client = MpvIpcClient(pipe)
    snap = _snapshot_mpv_slot(paths, slot_id)
    if not snap:
        print(json.dumps({"ok": False, "error": "Could not snapshot slot"}))
        return 1

    content = " ".join(args.text).strip()
    if not content:
        print("Usage: m note \"your thought...\"")
        return 1

    from datetime import datetime, UTC
    now = datetime.now(UTC).isoformat()
    
    # Capture position
    time_pos = snap.get("time_pos")
    chapter_meta = snap.get("chapter_metadata")
    chapter_title = chapter_meta.get("title") if isinstance(chapter_meta, dict) else None
    
    pos_str = ""
    if isinstance(time_pos, (int, float)):
        minutes = int(time_pos // 60)
        seconds = int(time_pos % 60)
        pos_str = f" [{minutes:02d}:{seconds:02d}]"
        if chapter_title:
            pos_str = f" ('{chapter_title}' at {minutes:02d}:{seconds:02d})"

    # Store the note in feedback_events with a specific kind 'note'
    # We prefix the note with the timestamp for easy reading
    full_note = f"{pos_str} {content}".strip()

    with db.connect(paths.db_path) as conn:
        tid, surl, skind = _upsert_from_snapshot(conn, snap)
        db.record_feedback_event(
            conn, 
            occurred_at=now,
            track_id=tid, 
            source_url=surl, 
            source_kind=skind, 
            kind="note",
            note=full_note
        )
    
    print(json.dumps({"ok": True, "track_id": tid, "note": full_note, "msg": "Musical thought recorded."}))
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    """Display the list of recorded musical thoughts/notes."""
    paths = _ensure_ready()
    _safe_sync_events(paths)
    
    query = """
        SELECT f.occurred_at, f.note, t.title, t.artist
        FROM feedback_events f
        JOIN tracks t ON t.id = f.track_id
        WHERE f.kind = 'note'
        ORDER BY f.occurred_at DESC
        LIMIT ?
    """
    
    with db.connect(paths.db_path) as conn:
        rows = conn.execute(query, (args.limit,)).fetchall()
        
        if not rows:
            print("Your musical journal is empty. Use 'm note' to record your first thought!")
            return 0
            
        print(f"--- Musical Journal (Last {len(rows)} entries) ---")
        for r in rows:
            # Format: [2024-03-05] Title - Artist: [01:23] My thought
            dt = r["occurred_at"].split("T")[0]
            print(f"[{dt}] {r['title']} - {r['artist'] or 'Unknown'}: {r['note']}")
    return 0


def cmd_init(_args: argparse.Namespace) -> int:
    _ensure_ready()
    print(json.dumps({"ok": True}))
    return 0


def cmd_sync_events(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    result = _safe_sync_events(paths)
    print(json.dumps(result))
    return 0


def cmd_rec(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    if not args.no_sync:
        _safe_sync_events(paths)

    with db.connect(paths.db_path) as conn:
        items = recommend(paths, conn, engine=args.engine, limit=args.limit, explain=args.why)
        filtered = _apply_rec_filters(
            items,
            exclude_artists=args.exclude_artist,
            exclude_tracks=args.exclude_track,
            min_score=args.min_score,
        )

        if args.json_out:
            print(json.dumps([asdict(i) for i in filtered], ensure_ascii=False))
        else:
            for i, item in enumerate(filtered):
                reason = f" [{item.reason}]" if item.reason else ""
                print(f"{i:2d}. {item.title} - {item.artist or 'Unknown'}{reason}")
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    _safe_sync_events(paths)
    with db.connect(paths.db_path) as conn:
        stats = db.stats_summary(conn)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    _safe_sync_events(paths)

    target_urls: list[str] = []
    if args.target:
        query = " ".join(args.target).strip()
        if query:
            targets = _run_yt_dlp_search_urls(query, max(int(args.queue), 1))
            print(f"Resolved search -> {targets[0]}")
            target_urls = targets
    else:
        with db.connect(paths.db_path) as conn:
            items = recommend(paths, conn, engine=args.engine, limit=args.queue, explain=args.why)
            filtered = _apply_rec_filters(
                items,
                exclude_artists=args.exclude_artist,
                exclude_tracks=args.exclude_track,
                min_score=args.min_score,
            )
            if not filtered:
                print("No recommendations found.")
                return 1
            if args.why:
                print("Queue reasons:")
                for i in filtered:
                    print(f"  - {i.title}: {i.reason}")
            target_urls = [i.source_url for i in filtered if i.source_url]

    if not target_urls:
        print("Nothing to play.")
        return 1

    reused_existing = False
    try:
        client = MpvIpcClient(pipe_for_slot(SLOT_PRIMARY, paths))
        _load_targets_into_client(client, target_urls)
        reused_existing = True
    except MpvIpcError:
        _restart_slot_with_targets(paths, SLOT_PRIMARY, target_urls)

    print(
        json.dumps(
            {"ok": True, "action": "replace", "slot": SLOT_PRIMARY, "targets": target_urls, "reused": reused_existing},
            ensure_ascii=False,
        )
    )
    return 0


def cmd_layer(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    _safe_sync_events(paths)
    query = " ".join(args.target).strip()
    if not query:
        print("Usage: m layer <URL or search query>", file=sys.stderr)
        return 1

    registry = clean_dead_slots(paths)
    if not registry:
        print("No active playback to layer onto.", file=sys.stderr)
        return 1

    url = _run_yt_dlp_print_url(query)
    print(f"Resolved search -> {url}")

    slot_id = next_slot_id(registry)

    proc = _launch_registered_slot(paths, [url], slot_id=slot_id)

    print(
        json.dumps(
            {
                "ok": True,
                "action": "layer",
                "slot": slot_id,
                "pid": int(proc.pid),
                "pipe": pipe_for_slot(slot_id, paths),
                "targets": [url],
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_current(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    if args.slot == "all":
        registry = clean_dead_slots(paths)
        out = {}
        for sid in sorted(registry.keys()):
            out[sid] = _snapshot_mpv_slot(paths, sid)
        print(json.dumps(out, ensure_ascii=False))
    else:
        if active_slot_info(paths, args.slot) is None:
            print(json.dumps({}, ensure_ascii=False))
            return 0
        snap = _snapshot_mpv_slot(paths, args.slot)
        print(json.dumps(snap, ensure_ascii=False))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    registry = clean_dead_slots(paths)

    # Resolve which slots to stop
    slots_to_stop = []
    if args.slot == "all":
        slots_to_stop = list(registry.keys())
    elif args.slot is None:
        # Default stop slot 0 if it exists
        if SLOT_PRIMARY in registry:
            slots_to_stop = [SLOT_PRIMARY]
    else:
        if args.slot in registry:
            slots_to_stop = [args.slot]

    if not slots_to_stop:
        if args.slot == "all":
            results = _stop_profile_orphans(paths, set())
            print(json.dumps({"ok": all(r["ok"] for r in results), "results": results}, ensure_ascii=False))
            return 0 if all(r["ok"] for r in results) else 1
        return 0

    results = []
    for sid in slots_to_stop:
        info = registry[sid]
        results.append({"slot": sid, "pid": info.pid, "ok": _stop_slot_instance(paths, sid, info)})

    if args.slot == "all":
        known_pids = {info.pid for info in registry.values()}
        results.extend(_stop_profile_orphans(paths, known_pids))

    print(json.dumps({"ok": all(r["ok"] for r in results), "results": results}, ensure_ascii=False))
    return 0 if all(r["ok"] for r in results) else 1


def cmd_pause(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    registry = clean_dead_slots(paths)
    if args.slot == "all":
        slots_to_update = list(registry.keys())
    else:
        slots_to_update = [args.slot]

    results = []
    for sid in slots_to_update:
        info = registry.get(sid)
        if not info:
            continue
        client = MpvIpcClient(info.pipe)
        try:
            paused = client.get_property("pause")
            client.command(["set_property", "pause", not paused])
            results.append({"slot": sid, "paused": not paused, "ok": True})
        except MpvIpcError:
            results.append({"slot": sid, "ok": False})

    print(json.dumps({"ok": any(r["ok"] for r in results), "results": results}))
    return 0


def cmd_slots(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    registry = clean_dead_slots(paths)
    out = []
    for sid in sorted(registry.keys()):
        info = registry[sid]
        title = None
        volume = None
        try:
            client = MpvIpcClient(info.pipe)
            title = client.get_property("media-title")
            volume = client.get_property("volume")
        except MpvIpcError:
            pass
        out.append({"slot": sid, "pid": info.pid, "pipe": info.pipe, "title": title, "volume": volume})
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    slot_id, pipe = _resolve_slot_pipe(paths, args.slot)
    client = MpvIpcClient(pipe)
    try:
        snap = _get_mpv_snapshot(paths, slot_id)
    except MpvIpcError:
        recovered, target_url = _recover_next_playback(paths, slot_id)
        if not recovered:
            print(json.dumps({"ok": False, "error": "Could not recover playback"}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "recovered": True, "target": target_url, "slot": slot_id}, ensure_ascii=False))
        return 0

    playlist_pos = snap.get("playlist_pos")
    playlist_count = snap.get("playlist_count")
    appended = 0
    if (
        isinstance(playlist_pos, (int, float))
        and isinstance(playlist_count, (int, float))
        and int(playlist_pos) >= int(playlist_count) - 1
    ):
        appended = _append_recommendations_to_slot(paths, slot_id, client=client)

    from datetime import UTC, datetime

    with db.connect(paths.db_path) as conn:
        tid, surl, skind = _upsert_from_snapshot(conn, snap)
        db.record_play_event(
            conn,
            occurred_at=datetime.now(UTC).isoformat(),
            track_id=tid,
            source_url=surl,
            source_kind=skind,
            action="next",
            reason="manual_next_cli",
            playback_time_sec=snap.get("time_pos") if isinstance(snap.get("time_pos"), (int, float)) else snap.get("playback_time"),
            duration_sec=snap.get("duration") if isinstance(snap.get("duration"), (int, float)) else None,
        )
        client.command(["playlist-next", "force"])

    print(json.dumps({"ok": True, "slot": slot_id, "appended": appended}, ensure_ascii=False))
    return 0


def cmd_good(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    slot_id, pipe = _resolve_slot_pipe(paths, args.slot)
    snap = _snapshot_mpv_slot(paths, slot_id)
    if not snap:
        print(json.dumps({"ok": False, "error": "Could not snapshot slot"}))
        return 1

    from datetime import datetime, UTC
    now = datetime.now(UTC).isoformat()
    
    # Capture current playback position and chapter for the note
    time_pos = snap.get("time_pos")
    chapter_meta = snap.get("chapter_metadata")
    chapter_title = chapter_meta.get("title") if isinstance(chapter_meta, dict) else None
    
    note = None
    if isinstance(time_pos, (int, float)):
        minutes = int(time_pos // 60)
        seconds = int(time_pos % 60)
        time_str = f"{minutes:02d}:{seconds:02d}"
        if chapter_title:
            note = f"'{chapter_title}' at {time_str}"
        else:
            note = f"marked at {time_str}"

    with db.connect(paths.db_path) as conn:
        tid, surl, skind = _upsert_from_snapshot(conn, snap)
        db.record_feedback_event(
            conn, 
            occurred_at=now,
            track_id=tid, 
            source_url=surl, 
            source_kind=skind, 
            kind="good",
            note=note
        )
    
    msg = f"Track {tid} marked as good"
    if note:
        msg += f" ({note})"
    print(json.dumps({"ok": True, "track_id": tid, "note": note, "msg": msg}))
    return 0


def cmd_bad(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    slot_id, pipe = _resolve_slot_pipe(paths, args.slot)
    client = MpvIpcClient(pipe)
    snap = _snapshot_mpv_slot(paths, slot_id)
    if not snap:
        print(json.dumps({"ok": False, "error": "Could not snapshot slot"}))
        return 1

    from datetime import datetime, UTC
    now = datetime.now(UTC).isoformat()

    with db.connect(paths.db_path) as conn:
        tid, surl, skind = _upsert_from_snapshot(conn, snap)
        db.record_feedback_event(
            conn, 
            occurred_at=now,
            track_id=tid, 
            source_url=surl, 
            source_kind=skind, 
            kind="bad"
        )
        client.command(["playlist-next", "force"])
    print(json.dumps({"ok": True, "track_id": tid, "action": "next"}))
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    if not args.no_sync:
        _safe_sync_events(paths)

    with db.connect(paths.db_path) as conn:
        event = db.pop_last_manual_event(conn)
        if not event:
            print(json.dumps({"ok": False, "error": "No recent manual event to undo"}))
            return 1

        if not args.db_only:
            if event["source_table"] == "play_events" and event["action"] == "next":
                try:
                    _, pipe = _resolve_slot_pipe(paths, args.slot)
                    client = MpvIpcClient(pipe)
                    client.command(["playlist-prev"])
                except Exception:
                    pass

        print(json.dumps({"ok": True, "undone": event}))
    return 0


def cmd_session_save(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    registry = clean_dead_slots(paths)
    if not registry:
        print(json.dumps({"ok": False, "error": "No active slots to save"}))
        return 1

    snaps = {}
    for sid in registry:
        snaps[sid] = _snapshot_mpv_slot(paths, sid)

    with db.connect(paths.db_path) as conn:
        db.save_session(conn, args.name, snaps)
    print(json.dumps({"ok": True, "session": args.name, "slots": list(snaps.keys())}))
    return 0


def cmd_session_load(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    with db.connect(paths.db_path) as conn:
        session = db.load_session(conn, args.name)
        if not session:
            print(json.dumps({"ok": False, "error": f"Session {args.name!r} not found"}))
            return 1

    # Kill existing slots mentioned in session to replace them
    for sid, snap in session.items():
        if not snap.get("path"):
            continue
        try:
            _restart_slot_with_targets(paths, sid, [snap["path"]])
        except MpvIpcError:
            print(json.dumps({"ok": False, "error": f"Could not restore slot {sid!r}"}))
            return 1

    print(json.dumps({"ok": True, "session": args.name, "slots": list(session.keys())}))
    return 0


def cmd_session_list(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    with db.connect(paths.db_path) as conn:
        names = db.list_sessions(conn)
    print(json.dumps(names))
    return 0


def cmd_session_delete(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    with db.connect(paths.db_path) as conn:
        db.delete_session(conn, args.name)
    print(json.dumps({"ok": True}))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    from .backup import export_backup

    result = export_backup(paths, args.out, include_events=args.include_events)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    from .backup import import_backup

    result = import_backup(paths, args.in_file, mode=args.mode)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_commands(_args: argparse.Namespace) -> int:
    print("Music Hub CLI Cheatsheet")
    print("------------------------")
    print("Playback:")
    print("  m play [query]    Search and play (e.g. m play 许巍)")
    print("  m next            Skip current song")
    print("  m stop [all]      Stop playback")
    print("  m vol [0-130]     Set volume")
    print("")
    print("Feedback:")
    print("  m good            Mark as loved")
    print("  m bad             Mark as hated (skips)")
    print("  m undo            Revert last manual action")
    print("")
    print("Discovery:")
    print("  m rec             Show recommendations")
    print("  m play            (no args) Start smart queue")
    print("")
    print("Natural Language Examples:")
    print('  m "播放 周杰伦"')
    print('  m "大点声"')
    print('  m "我想听点有深度的"')
    return 0


def cmd_vol(args: argparse.Namespace) -> int:
    """Set volume on a specific slot or all active slots. Range 0-130 (100=normal)."""
    paths = _ensure_ready()
    registry = clean_dead_slots(paths)

    if not registry:
        print("No active mpv slots.", file=sys.stderr)
        return 1

    level = max(0, min(130, int(args.level)))

    if args.slot == "all":
        slots_to_update = list(registry.values())
    else:
        info = registry.get(args.slot)
        if info is None:
            active = sorted(registry.keys())
            print(f"Slot {args.slot!r} not found. Active slots: {active}", file=sys.stderr)
            return 1
        slots_to_update = [info]

    results = []
    for info in slots_to_update:
        client = MpvIpcClient(info.pipe)
        try:
            resp = client.command(["set_property", "volume", level])
            ok = resp.get("error") == "success"
            results.append({"slot": info.slot_id, "volume": level, "ok": ok})
        except MpvIpcError as exc:
            results.append({"slot": info.slot_id, "error": str(exc), "ok": False})

    print(json.dumps({"ok": any(r["ok"] for r in results), "results": results}, ensure_ascii=False))
    return 0 if any(r["ok"] for r in results) else 1


def cmd_doctor(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "db_path": str(paths.db_path),
        "events_jsonl": str(paths.events_jsonl),
        "mpv_script_exists": paths.mpv_script.exists(),
        "mpv_exe": None,
        "yt_dlp_module": None,
        "ytmusicapi": False,
    }
    try:
        checks["mpv_exe"] = resolve_mpv_exe(paths)
    except Exception as exc:
        checks["mpv_exe"] = f"ERROR: {exc}"
    try:
        proc = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True, check=True)
        checks["yt_dlp_module"] = proc.stdout.strip() or "ok"
    except Exception as exc:
        checks["yt_dlp_module"] = f"ERROR: {exc}"
    try:
        import ytmusicapi  # type: ignore

        checks["ytmusicapi"] = getattr(ytmusicapi, "__version__", True)
    except Exception:
        checks["ytmusicapi"] = False
    st = daemon_status(paths)
    checks["daemon"] = {"running": st.running, "pid": st.pid, "owned": st.owned, "pid_file": str(st.pid_file)}
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0


def cmd_daemon_run(args: argparse.Namespace) -> int:
    _ensure_ready()
    return daemon_run_loop(get_paths(), poll_sec=args.poll_sec, once=args.once)


def cmd_daemon_start(args: argparse.Namespace) -> int:
    _ensure_ready()
    st = daemon_start(get_paths(), poll_sec=args.poll_sec)
    print(json.dumps({"running": st.running, "pid": st.pid, "owned": st.owned, "pid_file": str(st.pid_file)}, ensure_ascii=False))
    return 0 if st.running else 1


def cmd_daemon_stop(_args: argparse.Namespace) -> int:
    st = daemon_stop(get_paths())
    print(json.dumps({"running": st.running, "pid": st.pid, "owned": st.owned}, ensure_ascii=False))
    return 0


def cmd_daemon_status(_args: argparse.Namespace) -> int:
    st = daemon_status(get_paths())
    print(json.dumps({"running": st.running, "pid": st.pid, "owned": st.owned, "log_file": str(st.log_file)}, ensure_ascii=False))
    return 0


def cmd_sync_ytm(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    if args.json:
        result = import_json_file(paths, source_kind="ytmusic", json_file=args.json)
    else:
        result = import_ytm_live(paths, auth_json=args.auth_json, include_history=not args.no_history)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_sync_ncm(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    if not args.json:
        print(
            json.dumps(
                {
                    "source": "netease",
                    "error": "Please provide --json <export-file> for now.",
                    "hint": "You can export with your preferred tool, then import normalized JSON.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    result = import_ncm_json(paths, json_file=args.json)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_sync_all(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    out: dict[str, Any] = {"events": _safe_sync_events(paths)}
    if args.ytm_json or args.ytm_auth_json:
        if args.ytm_json:
            out["ytm"] = import_json_file(paths, source_kind="ytmusic", json_file=args.ytm_json).as_dict()
        else:
            out["ytm"] = import_ytm_live(paths, auth_json=args.ytm_auth_json, include_history=not args.no_history).as_dict()
    if args.ncm_json:
        out["ncm"] = import_ncm_json(paths, json_file=args.ncm_json).as_dict()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_train_implicit(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    _safe_sync_events(paths)
    result = train_implicit_cache(paths, topn=args.topn, k=args.k)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def cmd_train_all(args: argparse.Namespace) -> int:
    # Currently only implicit requires explicit training; rule engine is online.
    return cmd_train_implicit(args)


def cmd_ask(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    if not query:
        print("Usage: ask <natural language request>")
        return 1
    parsed = parse_freeform(query)
    if not parsed:
        print("Could not parse request.")
        return 1
    if args.explain:
        print(f"[ask] {parsed.reason} -> {' '.join(parsed.argv)}")
    return main(parsed.argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="musicctl", description="musichub CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="Initialize local DB/runtime dirs")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor", help="Check local environment and daemon status")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("sync-events", help="Ingest mpv Lua events JSONL")
    p.set_defaults(func=cmd_sync_events)

    p = sub.add_parser("rec", help="Show recommendations")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--no-sync", action="store_true")
    p.add_argument("--engine", choices=["auto", "rule", "implicit"], default="auto")
    p.add_argument("--why", action="store_true", help="Show recommendation reasons")
    p.add_argument("--exclude-artist", action="append", default=[], help="Exclude artist name (repeatable)")
    p.add_argument("--exclude-track", action="append", default=[], help="Exclude track title or ID (repeatable)")
    p.add_argument("--min-score", type=float, default=None, help="Only show recommendations with score >= value")
    p.add_argument("--json", dest="json_out", action="store_true", help="Output JSON")
    p.set_defaults(func=cmd_rec)

    p = sub.add_parser("stats", help="Show local stats/profile summary")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("note", help="Record a musical thought for the current track")
    p.add_argument("text", nargs="+", help="The content of your thought")
    p.add_argument("--slot", default=SLOT_PRIMARY)
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("journal", help="Review your musical journal")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_journal)

    p = sub.add_parser("radio", help="Infinite playback mode from current context")
    p.add_argument("--limit", type=int, default=5, help="Number of related tracks to fetch")
    p.set_defaults(func=cmd_radio)

    p = sub.add_parser("play", help="Play URL/query or recommendation queue")
    p.add_argument("target", nargs="*", help="URL, local file path, or search query")
    p.add_argument("--queue", type=int, default=5)
    p.add_argument("--engine", choices=["auto", "rule", "implicit"], default="auto")
    p.add_argument("--why", action="store_true", help="Show queue reasons before playback")
    p.add_argument("--exclude-artist", action="append", default=[], help="Exclude artist name (repeatable)")
    p.add_argument("--exclude-track", action="append", default=[], help="Exclude track title or ID (repeatable)")
    p.add_argument("--min-score", type=float, default=None, help="Only use recommendations with score >= value")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("layer", help="Layer a new mpv instance alongside existing ones")
    p.add_argument("target", nargs="*", help="URL or search query")
    p.set_defaults(func=cmd_layer)

    p = sub.add_parser("current", help="Show current mpv track via IPC")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID or 'all'")
    p.set_defaults(func=cmd_current)

    p = sub.add_parser("stop", help="Stop playback (specify slot or 'all'; default: slot 0)")
    p.add_argument("slot", nargs="?", default=None, help="Slot ID, 'all', or omit for slot 0")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("pause", help="Toggle pause/resume playback")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID or 'all'")
    p.set_defaults(func=cmd_pause)

    p = sub.add_parser("vol", help="Set volume for a slot or all slots (0-130, 100=normal)")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID or 'all'")
    p.add_argument("level", type=int, help="Volume level 0-130")
    p.set_defaults(func=cmd_vol)

    p = sub.add_parser("slots", help="List active mpv instances")
    p.set_defaults(func=cmd_slots)

    p = sub.add_parser("good", help="Mark current track good")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID")
    p.set_defaults(func=cmd_good)

    p = sub.add_parser("bad", help="Mark current track bad")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID")
    p.set_defaults(func=cmd_bad)

    p = sub.add_parser("next", help="Skip to next track")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("undo", help="Undo last manual feedback/next action")
    p.add_argument("slot", nargs="?", default=SLOT_PRIMARY, help="Slot ID (for next undo playback)")
    p.add_argument("--db-only", action="store_true", help="Only rollback DB event; do not control player")
    p.add_argument("--no-sync", action="store_true", help="Skip event sync before undo")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("commands", help="Show command cheatsheet and natural-language usage")
    p.set_defaults(func=cmd_commands)

    p_session = sub.add_parser("session", help="Save/load/list/delete playback sessions")
    session_sub = p_session.add_subparsers(dest="session_cmd", required=True)

    p = session_sub.add_parser("save", help="Save current playback session")
    p.add_argument("name", nargs="?", default="default")
    p.set_defaults(func=cmd_session_save)

    p = session_sub.add_parser("load", help="Load a saved playback session")
    p.add_argument("name", nargs="?", default="default")
    p.set_defaults(func=cmd_session_load)

    p = session_sub.add_parser("list", help="List saved sessions")
    p.set_defaults(func=cmd_session_list)

    p = session_sub.add_parser("delete", help="Delete a saved session")
    p.add_argument("name", nargs="?", default="default")
    p.set_defaults(func=cmd_session_delete)

    p = sub.add_parser("export", help="Export local DB/models into a backup ZIP")
    p.add_argument("--out", required=True, help="Output ZIP file")
    p.add_argument("--include-events", action="store_true", help="Also include raw mpv events log")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="Import backup ZIP into local data")
    p.add_argument("--in", dest="in_file", required=True, help="Input ZIP file")
    p.add_argument("--mode", choices=["replace"], default="replace")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("ask", help="Natural-language command parser")
    p.add_argument("query", nargs=argparse.REMAINDER)
    p.add_argument("--explain", action="store_true", help="Show parsed command before executing")
    p.set_defaults(func=cmd_ask)

    p_sync = sub.add_parser("sync", help="Import/sync events and platform data")
    sync_sub = p_sync.add_subparsers(dest="sync_cmd", required=True)

    p = sync_sub.add_parser("events", help="Sync mpv Lua events")
    p.set_defaults(func=cmd_sync_events)

    p = sync_sub.add_parser("ytm", help="Sync YouTube Music (live via ytmusicapi or JSON import)")
    p.add_argument("--auth-json", help="ytmusicapi auth JSON for live sync")
    p.add_argument("--json", help="Normalized JSON export file to import")
    p.add_argument("--no-history", action="store_true", help="Skip YTM history import in live mode")
    p.set_defaults(func=cmd_sync_ytm)

    p = sync_sub.add_parser("ncm", help="Sync NetEase Cloud Music from JSON export")
    p.add_argument("--json", help="Normalized JSON export file to import")
    p.set_defaults(func=cmd_sync_ncm)

    p = sync_sub.add_parser("all", help="Sync events and optional YTM/NCM imports")
    p.add_argument("--ytm-auth-json")
    p.add_argument("--ytm-json")
    p.add_argument("--ncm-json")
    p.add_argument("--no-history", action="store_true")
    p.set_defaults(func=cmd_sync_all)

    p_daemon = sub.add_parser("daemon", help="Background event ingestion daemon")
    daemon_sub = p_daemon.add_subparsers(dest="daemon_cmd", required=True)

    p = daemon_sub.add_parser("run", help="Run daemon loop in foreground (internal)")
    p.add_argument("--poll-sec", type=float, default=2.0)
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_daemon_run)

    p = daemon_sub.add_parser("start", help="Start daemon in background")
    p.add_argument("--poll-sec", type=float, default=2.0)
    p.set_defaults(func=cmd_daemon_start)

    p = daemon_sub.add_parser("stop", help="Stop daemon")
    p.set_defaults(func=cmd_daemon_stop)

    p = daemon_sub.add_parser("status", help="Daemon status")
    p.set_defaults(func=cmd_daemon_status)

    p_train = sub.add_parser("train", help="Train recommendation caches/models")
    train_sub = p_train.add_subparsers(dest="train_cmd", required=True)

    p = train_sub.add_parser("implicit", help="Train implicit recommendation cache (optional dependency)")
    p.add_argument("--topn", type=int, default=200)
    p.add_argument("-k", type=int, default=64, help="implicit BM25 neighborhood size")
    p.set_defaults(func=cmd_train_implicit)

    p = train_sub.add_parser("all", help="Train all configured models (currently implicit)")
    p.add_argument("--topn", type=int, default=200)
    p.add_argument("-k", type=int, default=64)
    p.set_defaults(func=cmd_train_all)

    return parser


def _dispatch_natural_language(argv: list[str]) -> int | None:
    if argv and str(argv[0]).startswith("-"):
        return None
    direct = maybe_extract_direct_command(argv)
    if direct is not None:
        return None
    text = " ".join(argv).strip()
    if not text:
        return None
    parsed = parse_freeform(text)
    if not parsed:
        return None
    print(f"[nl] {parsed.reason} -> {' '.join(parsed.argv)}")
    return main(parsed.argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    nl_result = _dispatch_natural_language(argv)
    if nl_result is not None:
        return nl_result

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="")
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        print(f"Command failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    except (MpvIpcError, FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    main()
