## v0.3.0

`music-hub` is becoming clearer about what it is:

it is a **Windows-first** local music CLI,
made for people who want a lightweight, one-click, local-first listening workflow,
and also for developers who may want to port it to macOS, Linux, or a GUI later.

This release is not mainly about adding more features.
It is about making the project smaller in feel, safer in behavior, and more coherent as a public tool.

### What's improved

- Fixed the broken command surface so `stats`, `undo`, `session`, `export`, and `import` work again with the current codebase
- Tightened playback behavior across `play`, `layer`, `slots`, `stop`, and `next`
- Removed the dangerous fallback where historical database entries could be mistaken for “currently playing”
- Isolated playback pipes by profile, so different local profiles no longer interfere with each other
- Improved `radio` so invalid imported YouTube-style links no longer break playback; when related videos fail, it now falls back to search
- Rewrote the README to better reflect the real identity of the project: minimal, local, Windows-first, and beginner-friendly

### Why this release matters

This release makes `music-hub` feel less like a pile of evolving scripts,
and more like a small, coherent tool you can actually use every day.

It is now safer in multi-profile scenarios, more reliable in core playback flows,
and much clearer about who it is for:

- Windows users
- beginners who want one-click setup
- people who want a quieter, more personal music workflow
- developers who want a small codebase they can continue shaping

### Project direction

`music-hub` is not trying to become a giant player.

It is a lightweight personal loop:

- play something quickly
- respond to it immediately
- keep the trace locally
- slowly turn that trace into a more personal listening workflow

If you want a minimal Windows music tool, start here.
If you want a base to fork into something else, start here too.
