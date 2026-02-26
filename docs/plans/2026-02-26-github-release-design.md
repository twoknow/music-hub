# music-hub GitHub Release Design

**Date:** 2026-02-26
**Goal:** Make music-hub usable by any Windows user or AI Agent via a single clone + one PowerShell command.

---

## Context

music-hub is a local-first music CLI that plays music via mpv (YouTube via yt-dlp), collects feedback (good/bad/next), stores history in SQLite, and generates recommendations. It has a natural-language interface in Chinese and English.

Current state: functional locally, no git, no public install path, one known bug (yt-dlp not found by mpv).

---

## Target

- **Audience:** Windows users + AI Agents (Claude Code, Cursor, Copilot, etc.)
- **Distribution:** GitHub + one-liner PowerShell install
- **Install UX:** `git clone ... && cd music-hub && .\install.ps1` — done

---

## Scope (5 items)

### 1. Bug fix: yt-dlp path in mpv_control.py

`launch_mpv` currently passes `--ytdl=yes` but doesn't tell mpv where yt-dlp lives.
mpv searches its own directory and PATH; if yt-dlp is only in Python Scripts, it silently fails.

**Fix:** Resolve yt-dlp path at launch time and pass `--ytdl-path=<path>` to mpv.
Resolution order: same dir as mpv.exe → `shutil.which("yt-dlp")` → skip flag if not found.

### 2. One-click install script: install.ps1

Steps (in order, with error stops):
1. Check Python 3.11+ — print download URL and exit if missing
2. Download latest mpv portable zip from mpv.io/builds (x86_64-20XXXXXX) → extract to `tools\mpv-portable\`
3. Download latest `yt-dlp.exe` from github.com/yt-dlp/yt-dlp/releases/latest → place in `tools\mpv-portable\`
4. `pip install -e .` (installs yt-dlp Python module + other deps)
5. Call `.\install-m-cli.ps1` to register global `m` command
6. Run `m doctor` — print success or failure summary

Must be idempotent: re-running overwrites cleanly without error.

### 3. AGENTS.md

Structured doc for AI agents. Sections:
- **Purpose** (one paragraph)
- **Prerequisites** (`m doctor` passes)
- **Command reference table** (command | purpose | example | output)
- **Decision guide** (when to call what)
- **Constraints** (don't call mpv directly; don't delete `data/`)

### 4. .gitignore

Exclude:
- `data/` (SQLite, logs, model cache — user-private)
- `tools/` (mpv portable + yt-dlp binaries — too large, re-downloaded at install)
- `__pycache__/`, `*.pyc`, `*.pyo`
- `*.egg-info/`

### 5. pyproject.toml dependencies

Add `[project.dependencies]`: `yt-dlp`, `requests`.
Add `[project.optional-dependencies]`: `recommend = ["numpy", "scipy", "implicit"]`.

---

## Out of scope

- Cross-platform support (macOS/Linux)
- PyPI publishing
- Tests / CI
- Compiled .exe distribution
- Moving the repo after install (document: don't move, re-run install.ps1 if you do)

---

## File changes summary

| File | Action |
|------|--------|
| `musichub/mpv_control.py` | Add `--ytdl-path` resolution |
| `install.ps1` | Create new |
| `AGENTS.md` | Create new |
| `.gitignore` | Create new |
| `pyproject.toml` | Add dependencies sections |
| `README.md` | Update Quick Start to use `install.ps1` |
