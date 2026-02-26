# music-hub GitHub Release Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make music-hub usable by any Windows user or AI Agent via `git clone` + `.\install.ps1`.

**Architecture:** Five self-contained changes — a Python bug fix, four new/updated files. No new modules. No tests (no test framework exists; each task has a manual verification step instead).

**Tech Stack:** Python 3.11+, PowerShell 5.1+, mpv portable, yt-dlp, SQLite

---

## Task 1: Fix yt-dlp path resolution in mpv_control.py

**Files:**
- Modify: `musichub/mpv_control.py`

**Context:** mpv searches its own directory and PATH for yt-dlp. If yt-dlp is only in Python's Scripts directory (common after `pip install yt-dlp`), mpv silently fails and produces no audio. Fix: resolve yt-dlp at launch time and pass `--ytdl-path` explicitly.

**Step 1: Add `_resolve_ytdlp` function**

Open `musichub/mpv_control.py`. After the imports, before `resolve_mpv_exe`, add:

```python
def _resolve_ytdlp(mpv_exe: str) -> str | None:
    """Find yt-dlp: alongside mpv, Python Scripts, or PATH."""
    import sys
    candidates = [
        Path(mpv_exe).parent / "yt-dlp.exe",
        Path(sys.executable).parent / "yt-dlp.exe",
        Path(sys.executable).parent / "Scripts" / "yt-dlp.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    on_path = shutil.which("yt-dlp")
    return on_path or None
```

Also add `from pathlib import Path` to the imports at the top (it's not currently imported).

**Step 2: Pass `--ytdl-path` in `launch_mpv`**

In `launch_mpv`, replace:
```python
        "--ytdl=yes",
```
with:
```python
        "--ytdl=yes",
        *([f"--ytdl-path={ytdlp}"] if (ytdlp := _resolve_ytdlp(mpv_exe)) else []),
```

**Step 3: Verify manually**

```powershell
cd C:\Users\mzmat\music-hub
python -c "from musichub.mpv_control import _resolve_ytdlp; print(_resolve_ytdlp(r'C:\Users\mzmat\tools\mpv-portable\mpv.exe'))"
```
Expected: prints a path ending in `yt-dlp.exe` (not `None`).

**Step 4: Commit**

```bash
git add musichub/mpv_control.py
git commit -m "fix: resolve yt-dlp path explicitly so mpv always finds it"
```

---

## Task 2: Create .gitignore

**Files:**
- Create: `.gitignore`

**Step 1: Create the file**

```gitignore
# User data (private, re-created at runtime)
data/

# Downloaded binaries (re-downloaded by install.ps1)
tools/

# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
dist/
build/

# Editor
.vscode/
.idea/
*.swp
```

**Step 2: Verify**

```bash
git status
```
Expected: `data/` and `tools/` do not appear as untracked.

**Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore"
```

---

## Task 3: Update pyproject.toml with dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies**

Replace the current `pyproject.toml` content with:

```toml
[project]
name = "musichub"
version = "0.1.0"
description = "Local music preference loop with mpv + yt-dlp + SQLite"
requires-python = ">=3.11"
dependencies = [
    "yt-dlp",
    "requests",
]

[project.optional-dependencies]
recommend = [
    "numpy",
    "scipy",
    "implicit",
]

[project.scripts]
musicctl = "musichub.cli:main"
m = "musichub.cli:main"
```

**Step 2: Verify**

```powershell
pip install -e .
```
Expected: installs cleanly, no errors.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add project dependencies to pyproject.toml"
```

---

## Task 4: Create install.ps1

**Files:**
- Create: `install.ps1`

**Context:** This is the main user-facing entry point. It must be idempotent (safe to re-run), give clear progress output, and stop with a helpful message on any failure.

**Step 1: Create the file**

```powershell
<#
.SYNOPSIS
    One-click setup for music-hub on Windows.
    Downloads mpv portable + yt-dlp, installs Python deps, registers global 'm' command.
.EXAMPLE
    .\install.ps1
#>
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # faster Invoke-WebRequest

$RepoRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsDir  = Join-Path $env:USERPROFILE "tools\mpv-portable"
$MpvExe    = Join-Path $ToolsDir "mpv.exe"
$YtdlpExe  = Join-Path $ToolsDir "yt-dlp.exe"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }

# --- 1. Check Python ---------------------------------------------------------
Write-Step "Checking Python 3.11+"
$pyver = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    Write-Host "Install from https://www.python.org/downloads/ then re-run this script."
    exit 1
}
$ver = [version]($pyver -replace 'Python ', '')
if ($ver -lt [version]"3.11") {
    Write-Host "ERROR: Python 3.11+ required (found $ver)" -ForegroundColor Red
    exit 1
}
Write-OK $pyver

# --- 2. Download mpv portable ------------------------------------------------
Write-Step "Setting up mpv portable -> $ToolsDir"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

if (Test-Path $MpvExe) {
    Write-OK "mpv.exe already present, skipping download"
} else {
    Write-Host "    Fetching latest mpv release info from GitHub..."
    $apiUrl  = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
    $headers = @{ "User-Agent" = "music-hub-installer" }
    try {
        $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers
        $asset   = $release.assets | Where-Object { $_.name -match "mpv-x86_64-.*\.7z$" } | Select-Object -First 1
        if (-not $asset) { throw "No x86_64 .7z asset found in release" }
        $zipPath = Join-Path $env:TEMP "mpv-portable.7z"
        Write-Host "    Downloading $($asset.name) ..."
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -Headers $headers
        Write-Host "    Extracting..."
        # Try 7z if available, else use built-in Expand-Archive fallback for zip
        $7z = "7z"
        if (-not (Get-Command $7z -ErrorAction SilentlyContinue)) {
            # Fallback: use Windows built-in for zip (won't work for .7z, warn user)
            Write-Warn "7z not found. Install 7-Zip and re-run, OR manually extract $zipPath to $ToolsDir"
            Write-Warn "Skipping mpv extraction. Install 7-Zip from https://www.7-zip.org/"
        } else {
            & $7z x $zipPath -o"$ToolsDir" -y | Out-Null
            Remove-Item $zipPath -Force
            Write-OK "mpv extracted to $ToolsDir"
        }
    } catch {
        Write-Warn "Could not auto-download mpv: $_"
        Write-Warn "Manual option: download portable build from https://mpv.io/installation/"
        Write-Warn "Extract mpv.exe to: $ToolsDir"
    }
}

# --- 3. Download yt-dlp.exe --------------------------------------------------
Write-Step "Setting up yt-dlp.exe -> $ToolsDir"
if (Test-Path $YtdlpExe) {
    Write-OK "yt-dlp.exe already present, skipping download"
} else {
    $ytUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    Write-Host "    Downloading yt-dlp.exe ..."
    try {
        Invoke-WebRequest -Uri $ytUrl -OutFile $YtdlpExe
        Write-OK "yt-dlp.exe saved to $ToolsDir"
    } catch {
        Write-Warn "Could not download yt-dlp.exe: $_"
        Write-Warn "Manual option: https://github.com/yt-dlp/yt-dlp/releases/latest"
    }
}

# --- 4. Install Python dependencies ------------------------------------------
Write-Step "Installing Python dependencies (pip install -e .)"
Push-Location $RepoRoot
try {
    python -m pip install -e . --quiet
    Write-OK "Python deps installed"
} finally {
    Pop-Location
}

# --- 5. Register global 'm' command ------------------------------------------
Write-Step "Registering global 'm' command"
Push-Location $RepoRoot
try {
    & ".\install-m-cli.ps1"
    Write-OK "'m' command registered"
} finally {
    Pop-Location
}

# --- 6. Verify ---------------------------------------------------------------
Write-Step "Running 'm doctor' to verify setup"
Push-Location $RepoRoot
try {
    & ".\m.ps1" doctor
} finally {
    Pop-Location
}

Write-Host "`n==> Setup complete! Try:" -ForegroundColor Green
Write-Host "    m `"play meditation music`""
Write-Host "    m `"播放 周杰伦 稻香`""
```

**Step 2: Verify manually**

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force   # once only if needed
.\install.ps1
```
Expected: Each step prints `OK:` or a clear `WARN:` with instructions. Ends with `m doctor` output showing mpv found.

**Step 3: Commit**

```bash
git add install.ps1
git commit -m "feat: add one-click install.ps1 (downloads mpv + yt-dlp, wires up 'm' command)"
```

---

## Task 5: Create AGENTS.md

**Files:**
- Create: `AGENTS.md`

**Context:** This file is specifically for AI agents (Claude Code, Cursor, GitHub Copilot, etc.). It tells them what the tool does, how to call it, and what the output means — without the prose of a human README.

**Step 1: Create the file**

```markdown
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
```

**Step 2: Verify**

Open `AGENTS.md` and confirm it renders cleanly as a markdown table. Check that all commands match what `m --help` (or `m play --help`) outputs.

**Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: add AGENTS.md for AI agent consumption"
```

---

## Task 6: Update README.md Quick Start

**Files:**
- Modify: `README.md`

**Context:** The current Quick Start references `m.ps1 init` and `install-m-cli.ps1` directly. Replace with the new `install.ps1` one-liner. Keep all other content.

**Step 1: Replace the Quick Start section**

Find the `## Quick Start` section and replace it with:

```markdown
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
```

**Step 2: Verify**

Preview README.md and confirm the Quick Start section is correct.

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README Quick Start to use install.ps1"
```

---

## Task 7: Initialize GitHub repo and push

**Step 1: Create repo on GitHub**

Go to https://github.com/new and create a new public repo named `music-hub`. Do NOT initialize with README (we have one).

**Step 2: Add remote and push**

```bash
git remote add origin https://github.com/YOUR_USERNAME/music-hub.git
git branch -M main
git push -u origin main
```

**Step 3: Verify**

Open the GitHub repo page. Confirm:
- `AGENTS.md` is visible at root
- `install.ps1` is visible at root
- `data/` and `tools/` are NOT listed (excluded by .gitignore)
- README renders correctly with the new Quick Start

---

## Summary of commits

```
fix: resolve yt-dlp path explicitly so mpv always finds it
chore: add .gitignore
chore: add project dependencies to pyproject.toml
feat: add one-click install.ps1 (downloads mpv + yt-dlp, wires up 'm' command)
docs: add AGENTS.md for AI agent consumption
docs: update README Quick Start to use install.ps1
```
