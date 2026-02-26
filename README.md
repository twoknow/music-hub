# musichub (MVP)

Local-first music workflow for:

- playing music via `mpv` (YouTube / YouTube Music URLs)
- collecting preference feedback (`good` / `bad` / `next`)
- storing events in SQLite
- generating simple recommendations

This MVP focuses on the daily feedback loop first. Importers (NetEase / YTM) can be added later.

## Quick Start

```powershell
git clone https://github.com/YOUR_USERNAME/music-hub
cd music-hub
.\install.ps1
```

This downloads mpv + yt-dlp, installs Python dependencies, and registers the global `m` command.
If `.\install.ps1` is blocked by execution policy, run this first:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

Then play something:

```powershell
m "play meditation music"
m "播放 周杰伦 稻香"
```

In the mpv window:

- `g` = good (like)
- `b` = bad
- `n` = next

Then ingest Lua-logged events (or start the daemon so this happens automatically):

```powershell
.\m.ps1 daemon start
.\m.ps1 "给我推荐"
.\m.ps1 stats
```

## Natural Language CLI (Chinese / English)

`m` supports freeform text. Unknown input is parsed as a music intent.
When you say `播放 ...` with specific content, it prefers YouTube search playback (via `yt-dlp ytsearch1`) before recommendation mode.

Examples:

```powershell
.\m.ps1 "播放 周杰伦 稻香"
.\m.ps1 "给我推荐"
.\m.ps1 "播放推荐"
.\m.ps1 "这首好歌"
.\m.ps1 "不喜欢这首"
.\m.ps1 "下一首"
.\m.ps1 "当前播放"
.\m.ps1 "启动后台同步"
.\m.ps1 "停止后台同步"
```

You can still use explicit commands:

```powershell
.\m.ps1 doctor
.\m.ps1 rec --limit 20
.\m.ps1 sync events
.\m.ps1 sync ytm --auth-json .\browser_auth.json
.\m.ps1 sync ytm --json .\ytm_export.json
.\m.ps1 sync ncm --json .\netease_export.json
.\m.ps1 train implicit
.\m.ps1 rec --engine auto --why
.\m.ps1 play --engine auto --why
```

## JSON Import Format (YTM / NCM)

For `sync ytm --json` / `sync ncm --json`, use a JSON array or object (`items` / `tracks` / `songs`) with fields like:

```json
[
  {
    "title": "Song Name",
    "artist": "Artist Name",
    "url": "https://music.youtube.com/watch?v=xxxxx",
    "duration_sec": 245,
    "liked": true,
    "disliked": false,
    "play_count": 12,
    "time": "2026-02-25T10:00:00Z"
  }
]
```

## Training (Optional `implicit`)

Rule recommendations work without any extra dependency.

If you want co-occurrence based recommendations (session/day contexts), install optional dependencies:

```powershell
pip install numpy scipy implicit
```

Then train and use the implicit cache:

```powershell
.\m.ps1 train implicit
.\m.ps1 rec --engine implicit --why
.\m.ps1 rec --engine auto --why
```

`--engine auto` will use `implicit` cache when available, otherwise fall back to the online rule engine.

## Daemon

The daemon tails `mpv` Lua event logs and ingests them into SQLite automatically.

```powershell
.\m.ps1 daemon start
.\m.ps1 daemon status
.\m.ps1 daemon stop
```

Foreground (debug):

```powershell
.\m.ps1 daemon run --poll-sec 1
```

If `daemon start` immediately reports not running in sandboxed environments, use foreground mode (`daemon run`) in a normal local terminal to verify behavior.
