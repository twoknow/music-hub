from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db
from .config import ensure_dirs, get_paths
from .daemon import run_loop as daemon_run_loop
from .daemon import start as daemon_start
from .daemon import status as daemon_status
from .daemon import stop as daemon_stop
from .events_ingest import ingest_mpv_events
from .importers import import_ncm_json, import_ytm_live, import_json_file
from .models import train_implicit_cache
from .mpv_control import launch_mpv, resolve_mpv_exe
from .mpv_ipc import MpvIpcClient, MpvIpcError
from .nl import maybe_extract_direct_command, parse_freeform
from .recommender import recommend as get_recommendations


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


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


def _pick_artist(meta: dict[str, Any]) -> str | None:
    for key in ("artist", "ARTIST", "Artist", "album_artist", "ALBUMARTIST", "uploader"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _get_mpv_snapshot(client: MpvIpcClient) -> dict[str, Any]:
    metadata = client.get_property("metadata") or {}
    return {
        "time": _now_iso(),
        "path": client.get_property("path"),
        "media_title": client.get_property("media-title"),
        "playback_time": client.get_property("playback-time"),
        "duration": client.get_property("duration"),
        "playlist_pos": client.get_property("playlist-pos"),
        "playlist_count": client.get_property("playlist-count"),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _run_yt_dlp_print_url(query: str) -> str:
    cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--print", "webpage_url", f"ytsearch1:{query}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("http"):
            return line
    raise RuntimeError(f"No URL returned from yt-dlp search for query: {query}")


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


def cmd_init(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    print(f"Initialized database: {paths.db_path}")
    print(f"Events JSONL: {paths.events_jsonl}")
    print(f"Daemon PID: {paths.daemon_pid_file}")
    print(f"mpv script: {paths.mpv_script}")
    return 0


def cmd_sync_events(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    result = _safe_sync_events(paths)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_rec(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    if not args.no_sync:
        _safe_sync_events(paths)
    conn = db.connect(paths.db_path)
    try:
        rows = get_recommendations(paths, conn, engine=args.engine, limit=args.limit, explain=args.why)
    finally:
        conn.close()
    if not rows:
        print("No recommendations yet (or implicit cache unavailable). Play/import data first, then train if needed.")
        return 0
    if args.json_out:
        print(json.dumps([r.as_dict() for r in rows], ensure_ascii=False, indent=2))
        return 0
    for i, r in enumerate(rows, 1):
        line = f"{i:2d}. {r.title} - {r.artist or '<unknown>'} | score={r.score:.2f} | {r.source_url or '<no-source>'} | engine={r.engine}"
        if args.why and r.reason:
            line += f" | why={r.reason}"
        print(line)
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    _safe_sync_events(paths)
    conn = db.connect(paths.db_path)
    try:
        stats = db.stats_summary(conn)
    finally:
        conn.close()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    _safe_sync_events(paths)

    if args.target:
        if _is_url(args.target):
            targets = [args.target]
        elif Path(args.target).expanduser().exists():
            targets = [str(Path(args.target).expanduser().resolve())]
        else:
            url = _run_yt_dlp_print_url(args.target)
            print(f"Resolved search -> {url}")
            targets = [url]
    else:
        conn = db.connect(paths.db_path)
        try:
            recs = get_recommendations(paths, conn, engine=args.engine, limit=max(args.queue, 1), explain=args.why)
        finally:
            conn.close()
        targets = [r.source_url for r in recs if r.source_url]
        if not targets:
            print('No playable recommendations. Seed data first with `m "播放 周杰伦 稻香"`.')
            return 1
        if args.why:
            for i, r in enumerate(recs, 1):
                if not r.source_url:
                    continue
                print(f"{i:2d}. {r.title} - {r.artist or '<unknown>'} | engine={r.engine} | why={r.reason or '-'}")

    proc = launch_mpv(paths, targets)
    print(f"mpv started (pid={proc.pid})")
    return 0


def cmd_current(_args: argparse.Namespace) -> int:
    client = MpvIpcClient(get_paths().mpv_pipe)
    print(json.dumps(_get_mpv_snapshot(client), ensure_ascii=False, indent=2))
    return 0


def _record_feedback(kind: str) -> int:
    paths = _ensure_ready()
    client = MpvIpcClient(paths.mpv_pipe)
    snap = _get_mpv_snapshot(client)
    conn = db.connect(paths.db_path)
    try:
        track_id, source_url, source_kind = _upsert_from_snapshot(conn, snap)
        db.record_feedback_event(
            conn,
            occurred_at=_now_iso(),
            track_id=track_id,
            source_url=source_url,
            source_kind=source_kind,
            kind=kind,
        )
        conn.commit()
    finally:
        conn.close()
    try:
        client.show_text("GOOD" if kind == "good" else "BAD")
    except MpvIpcError:
        pass
    print(json.dumps({"ok": True, "kind": kind, "path": snap.get("path")}, ensure_ascii=False))
    return 0


def cmd_good(_args: argparse.Namespace) -> int:
    return _record_feedback("good")


def cmd_bad(_args: argparse.Namespace) -> int:
    return _record_feedback("bad")


def cmd_next(_args: argparse.Namespace) -> int:
    paths = _ensure_ready()
    client = MpvIpcClient(paths.mpv_pipe)
    snap = _get_mpv_snapshot(client)
    conn = db.connect(paths.db_path)
    try:
        track_id, source_url, source_kind = _upsert_from_snapshot(conn, snap)
        db.record_play_event(
            conn,
            occurred_at=_now_iso(),
            track_id=track_id,
            source_url=source_url,
            source_kind=source_kind,
            action="next",
            reason="manual_next_cli",
            playback_time_sec=float(snap["playback_time"]) if isinstance(snap.get("playback_time"), (int, float)) else None,
            duration_sec=float(snap["duration"]) if isinstance(snap.get("duration"), (int, float)) else None,
        )
        conn.commit()
    finally:
        conn.close()
    client.command(["playlist-next", "force"])
    try:
        client.show_text("NEXT")
    except MpvIpcError:
        pass
    print(json.dumps({"ok": True, "action": "next", "path": snap.get("path")}, ensure_ascii=False))
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    client = MpvIpcClient(get_paths().mpv_pipe)
    client.command(["quit"])
    print(json.dumps({"ok": True, "action": "stop"}, ensure_ascii=False))
    return 0


def cmd_pause(_args: argparse.Namespace) -> int:
    client = MpvIpcClient(get_paths().mpv_pipe)
    client.command(["cycle", "pause"])
    try:
        client.show_text("PAUSE")
    except MpvIpcError:
        pass
    print(json.dumps({"ok": True, "action": "pause"}, ensure_ascii=False))
    return 0


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
    checks["daemon"] = {"running": st.running, "pid": st.pid, "pid_file": str(st.pid_file)}
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0


def cmd_daemon_run(args: argparse.Namespace) -> int:
    _ensure_ready()
    return daemon_run_loop(get_paths(), poll_sec=args.poll_sec, once=args.once)


def cmd_daemon_start(args: argparse.Namespace) -> int:
    _ensure_ready()
    st = daemon_start(get_paths(), poll_sec=args.poll_sec)
    print(json.dumps({"running": st.running, "pid": st.pid, "pid_file": str(st.pid_file)}, ensure_ascii=False))
    return 0 if st.running else 1


def cmd_daemon_stop(_args: argparse.Namespace) -> int:
    st = daemon_stop(get_paths())
    print(json.dumps({"running": st.running, "pid": st.pid}, ensure_ascii=False))
    return 0


def cmd_daemon_status(_args: argparse.Namespace) -> int:
    st = daemon_status(get_paths())
    print(json.dumps({"running": st.running, "pid": st.pid, "log_file": str(st.log_file)}, ensure_ascii=False))
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
    p.add_argument("--json", dest="json_out", action="store_true", help="Output JSON")
    p.set_defaults(func=cmd_rec)

    p = sub.add_parser("stats", help="Show local stats/profile summary")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("play", help="Play URL/query or recommendation queue")
    p.add_argument("target", nargs="?", help="URL, local file path, or search query")
    p.add_argument("--queue", type=int, default=5)
    p.add_argument("--engine", choices=["auto", "rule", "implicit"], default="auto")
    p.add_argument("--why", action="store_true", help="Show queue reasons before playback")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("current", help="Show current mpv track via IPC")
    p.set_defaults(func=cmd_current)

    p = sub.add_parser("stop", help="Stop playback and quit mpv")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("pause", help="Toggle pause/resume playback")
    p.set_defaults(func=cmd_pause)

    p = sub.add_parser("good", help="Mark current track good")
    p.set_defaults(func=cmd_good)

    p = sub.add_parser("bad", help="Mark current track bad")
    p.set_defaults(func=cmd_bad)

    p = sub.add_parser("next", help="Skip to next track")
    p.set_defaults(func=cmd_next)

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
    raise SystemExit(main())
