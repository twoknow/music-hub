# AGENTS.md — music-hub interface for AI agents

## What this tool does

`m` is a local music CLI for Windows. It plays music (YouTube search or URL) via mpv,
records your listening history and feedback in SQLite, and recommends songs based on that history.

## Prerequisites

Run `m doctor` first. If all checks pass, the tool is ready. If not, see README.md setup.

## Command reference

| Command | What it does | Example |
|---------|-------------|---------|
| `m "<search query>"` | Search YouTube and play immediately | `m "lofi hip hop"` |
| `m play "<query>"` | Same as above (explicit) | `m play "周杰伦 稻香"` |
| `m play <URL>` | Play a specific YouTube/YTM URL | `m play https://youtu.be/xxx` |
| `m play` | Play recommendation queue (requires history) | `m play` |
| `m rec` | List top recommendations without playing | `m rec --limit 10` |
| `m good` | Mark currently playing track as liked | `m good` |
| `m bad` | Mark currently playing track as disliked | `m bad` |
| `m next` | Skip to next track | `m next` |
| `m stop` | Stop playback and quit mpv | `m stop` |
| `m pause` | Toggle pause / resume | `m pause` |
| `m current` | Show what's playing now (JSON) | `m current` |
| `m stats` | Show listening stats summary (JSON) | `m stats` |
| `m daemon start` | Start background event sync daemon | `m daemon start` |
| `m daemon stop` | Stop daemon | `m daemon stop` |
| `m daemon status` | Check if daemon is running (JSON) | `m daemon status` |
| `m doctor` | Check environment (mpv, yt-dlp, Python) | `m doctor` |
| `m sync events` | Manually ingest mpv event log into SQLite | `m sync events` |

## Natural language aliases (Chinese + English)

The `m` command understands freeform text. Examples:

```
m "play meditation music"
m "冥想音乐"
m "下一首"
m "这首好听"
m "不喜欢这首"
m "给我推荐"
m "当前播放什么"
```

## Output formats

- `m current` → JSON with `path`, `media_title`, `playback_time`, `duration`, `metadata`
- `m stats` → JSON with play counts, top artists, session counts
- `m rec` → numbered list: `N. Title - Artist | score=X.XX | url | engine=rule`
- `m doctor` → JSON with `mpv_exe`, `yt_dlp_module`, `daemon` status

## Decision guide

```
User wants to play music?
  → m "<query or URL>"

Music is playing and user says they like it?
  → m good

Music is playing and user wants to skip?
  → m next

User wants to stop music entirely?
  → m stop

User wants to pause / resume?
  → m pause

User wants to know what's playing?
  → m current

User wants recommendations without auto-playing?
  → m rec

Something seems broken?
  → m doctor
```

## Constraints

- Do NOT call mpv directly. Always go through `m`.
- Do NOT modify or delete the `data/` directory. It contains the user's listening history.
- `m good` / `m bad` / `m next` / `m current` require mpv to already be running (started by `m play`).
- The tool is Windows-only. Do not attempt to run on macOS/Linux.
