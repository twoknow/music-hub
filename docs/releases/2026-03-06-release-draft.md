# GitHub Release Draft

## Suggested Title

Windows-first refresh: simpler setup, safer playback, clearer project identity

## Suggested Tag

Decide when publishing.

- If you treat this as a feature release: `v0.3.0`
- If you treat this as a stabilization release after `v0.2.0`: `v0.2.1`

## Release Notes

`music-hub` is becoming clearer about what it is:

- a **Windows-first** music CLI
- friendly enough for **non-technical users**
- local-first by default
- small enough to be forked into a macOS or Linux version later

This update is mainly about making the project usable, presentable, and trustworthy as a public repository.

### Highlights

- Fixed the broken command surface so `stats`, `undo`, `session`, `export`, and `import` work again with the current codebase
- Tightened playback behavior so `play`, `layer`, `slots`, `stop`, and `next` behave consistently
- Removed the dangerous fallback where historical DB entries could be mistaken for “currently playing”
- Isolated playback pipes by profile, so different local profiles no longer interfere with each other
- Improved `radio` so invalid imported YouTube-style links no longer break the flow; when related videos fail, it falls back to search
- Rewrote the README to better reflect the real identity of the project: minimal, local, Windows-first, and open to adaptation

### User-facing improvements

- better day-to-day CLI behavior
- safer multi-profile use
- cleaner session and backup workflow
- more reliable `radio`
- clearer onboarding for first-time users

### Developer-facing improvements

- stronger regression coverage
- fixed `pytest` collection issues
- clearer repository presentation on GitHub
- easier base for future ports or UI layers

### Positioning

This is not trying to become a giant player.

`music-hub` is a small personal tool for a simple loop:
play something, respond to it, keep the trace local, and slowly turn that into a more personal listening workflow.

If you want a lightweight Windows tool, start here.
If you want a small codebase to fork into something else, start here too.
