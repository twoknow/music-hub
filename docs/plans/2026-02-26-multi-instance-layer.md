# Multi-Instance Layer & Volume Control Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix `m play` to replace existing playback instead of spawning duplicate mpv instances, add `m layer` for intentional overlay, and add `m vol` for per-slot volume control.

**Architecture:** Introduce a slot registry (`data/runtime/mpv_slots.json`) that tracks each mpv instance by slot ID, pipe name, and PID. Slot 0 uses the existing primary pipe `\\.\pipe\musichub-mpv` for backward compatibility. `m play` tries IPC first and uses `loadfile replace` if mpv is already running; only launches a new process when no instance exists. `m layer` always launches a new instance on the next available slot.

**Tech Stack:** Python stdlib only — `json`, `os`, `ctypes` (for Windows PID check). No new dependencies. All changes in `musichub/` package.

---

### Task 1: slots.py — instance registry module

**Files:**
- Create: `musichub/slots.py`
- Create: `tests/test_slots.py`

**Context:** This module manages the JSON registry that maps slot IDs to mpv pipe names and PIDs. Slot 0 is primary (uses the legacy pipe name). All other commands will import from here.

**Step 1: Write the failing test**

Create `tests/test_slots.py`:

```python
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Make sure musichub is importable from the project root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.slots import (
    pipe_for_slot, next_slot_id, SlotInfo,
    load_registry, save_registry, clean_dead_slots,
    register_slot, unregister_slot, SLOT_PRIMARY,
)


def make_paths(tmp_path):
    """Minimal AppPaths-like object for tests."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    obj = MagicMock()
    obj.runtime_dir = runtime
    return obj


def test_pipe_for_primary_slot():
    assert pipe_for_slot(SLOT_PRIMARY) == r"\\.\pipe\musichub-mpv"


def test_pipe_for_secondary_slot():
    assert pipe_for_slot("1") == r"\\.\pipe\musichub-mpv-1"
    assert pipe_for_slot("2") == r"\\.\pipe\musichub-mpv-2"


def test_load_registry_empty(tmp_path):
    paths = make_paths(tmp_path)
    assert load_registry(paths) == {}


def test_save_and_load_registry(tmp_path):
    paths = make_paths(tmp_path)
    registry = {
        "0": SlotInfo(slot_id="0", pipe=r"\\.\pipe\musichub-mpv", pid=1234),
    }
    save_registry(paths, registry)
    loaded = load_registry(paths)
    assert loaded["0"].pid == 1234
    assert loaded["0"].pipe == r"\\.\pipe\musichub-mpv"


def test_next_slot_id_empty():
    assert next_slot_id({}) == "0"


def test_next_slot_id_skips_occupied():
    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 2),
    }
    assert next_slot_id(registry) == "2"


def test_register_and_unregister(tmp_path):
    paths = make_paths(tmp_path)
    register_slot(paths, "0", r"\\.\pipe\musichub-mpv", 9999)
    assert load_registry(paths)["0"].pid == 9999

    unregister_slot(paths, "0")
    assert "0" not in load_registry(paths)


def test_clean_dead_slots_removes_dead_pid(tmp_path):
    paths = make_paths(tmp_path)
    # Use PID 99999999 which almost certainly doesn't exist
    register_slot(paths, "0", r"\\.\pipe\musichub-mpv", 99999999)
    register_slot(paths, "1", r"\\.\pipe\musichub-mpv-1", 99999998)

    alive = clean_dead_slots(paths)
    # Both fake PIDs should be gone
    assert "0" not in alive
    assert "1" not in alive


def test_clean_dead_slots_keeps_current_process(tmp_path):
    paths = make_paths(tmp_path)
    my_pid = os.getpid()
    register_slot(paths, "0", r"\\.\pipe\musichub-mpv", my_pid)

    alive = clean_dead_slots(paths)
    assert "0" in alive
```

**Step 2: Run test to verify it fails**

```
cd C:\Users\mzmat\music-hub
python -m pytest tests/test_slots.py -v
```

Expected: `ImportError: cannot import name 'pipe_for_slot' from 'musichub.slots'` (module doesn't exist)

**Step 3: Write implementation**

Create `musichub/slots.py`:

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppPaths

SLOT_PRIMARY = "0"


@dataclass
class SlotInfo:
    slot_id: str
    pipe: str
    pid: int


def pipe_for_slot(slot_id: str) -> str:
    """Return named pipe path for a given slot ID."""
    if slot_id == SLOT_PRIMARY:
        return r"\\.\pipe\musichub-mpv"
    return rf"\\.\pipe\musichub-mpv-{slot_id}"


def _registry_path(paths: AppPaths) -> Path:
    return Path(paths.runtime_dir) / "mpv_slots.json"


def load_registry(paths: AppPaths) -> dict[str, SlotInfo]:
    p = _registry_path(paths)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: SlotInfo(**v) for k, v in data.items()}
    except Exception:
        return {}


def save_registry(paths: AppPaths, registry: dict[str, SlotInfo]) -> None:
    p = _registry_path(paths)
    p.write_text(
        json.dumps({k: asdict(v) for k, v in registry.items()}, indent=2),
        encoding="utf-8",
    )


def _is_alive(pid: int) -> bool:
    """Check if a PID is alive (Windows + POSIX compatible)."""
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clean_dead_slots(paths: AppPaths) -> dict[str, SlotInfo]:
    """Remove slots whose PIDs are no longer alive. Returns cleaned registry."""
    registry = load_registry(paths)
    alive = {k: v for k, v in registry.items() if _is_alive(v.pid)}
    if len(alive) != len(registry):
        save_registry(paths, alive)
    return alive


def next_slot_id(registry: dict[str, SlotInfo]) -> str:
    """Find the lowest unused slot ID (as string integer)."""
    for i in range(100):
        if str(i) not in registry:
            return str(i)
    raise RuntimeError("Too many active mpv slots (max 100)")


def register_slot(paths: AppPaths, slot_id: str, pipe: str, pid: int) -> None:
    registry = load_registry(paths)
    registry[slot_id] = SlotInfo(slot_id=slot_id, pipe=pipe, pid=pid)
    save_registry(paths, registry)


def unregister_slot(paths: AppPaths, slot_id: str) -> None:
    registry = load_registry(paths)
    registry.pop(slot_id, None)
    save_registry(paths, registry)
```

**Step 4: Run tests to verify pass**

```
python -m pytest tests/test_slots.py -v
```

Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add musichub/slots.py tests/test_slots.py
git commit -m "feat: add slots registry for multi-instance mpv tracking"
```

---

### Task 2: Fix `m play` — replace instead of spawn

**Files:**
- Modify: `musichub/cli.py` (lines 154-185, `cmd_play`)
- Modify: `musichub/mpv_control.py` (add `slot_id` param to `launch_mpv`)

**Context:** When `m play "query"` runs and mpv is already running on slot 0, we should send `loadfile <url> replace` via IPC instead of spawning a new process. Only spawn new mpv when no instance is running. Also register the slot after spawning.

**Step 1: Write the failing test**

Add to `tests/test_slots.py` (or create `tests/test_cmd_play_replace.py`):

```python
# tests/test_cmd_play_replace.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_play
import argparse


def _args(target="https://youtu.be/test123"):
    ns = argparse.Namespace()
    ns.target = target
    ns.queue = 5
    ns.engine = "auto"
    ns.why = False
    return ns


def test_play_replaces_existing_mpv():
    """When mpv is already running, loadfile is sent instead of launching new process."""
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client) as MockIpc, \
         patch("musichub.cli.launch_mpv") as mock_launch:

        result = cmd_play(_args())

    assert result == 0
    # loadfile replace was sent
    mock_client.command.assert_called_once_with(["loadfile", "https://youtu.be/test123", "replace"])
    # NO new process launched
    mock_launch.assert_not_called()


def test_play_launches_when_no_mpv():
    """When no mpv running, a new process is launched."""
    from musichub.mpv_ipc import MpvIpcError

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.MpvIpcClient") as MockIpc, \
         patch("musichub.cli.launch_mpv") as mock_launch, \
         patch("musichub.cli.register_slot"):

        MockIpc.return_value.command.side_effect = MpvIpcError("no mpv")
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_launch.return_value = mock_proc

        result = cmd_play(_args())

    assert result == 0
    mock_launch.assert_called_once()
```

**Step 2: Run to verify fails**

```
python -m pytest tests/test_cmd_play_replace.py -v
```

Expected: FAIL — `cmd_play` always calls `launch_mpv`, never sends `loadfile`

**Step 3: Implement**

In `musichub/mpv_control.py`, add `slot_id` parameter to `launch_mpv`:

```python
# Change signature from:
def launch_mpv(paths: AppPaths, targets: list[str]) -> subprocess.Popen[str]:

# To:
def launch_mpv(paths: AppPaths, targets: list[str], slot_id: str = "0") -> subprocess.Popen[str]:
    from .slots import pipe_for_slot
    ensure_dirs(paths)
    mpv_exe = resolve_mpv_exe(paths)
    pipe = pipe_for_slot(slot_id)          # <-- dynamic pipe per slot
    args = [
        mpv_exe,
        "--no-video",
        f"--input-ipc-server={pipe}",      # <-- use slot pipe
        f"--script={paths.mpv_script}",
        f"--script-opts=musichub-events_file={paths.events_jsonl}",
        "--ytdl=yes",
    ]
    args.extend(targets)
    env = os.environ.copy()
    ytdlp = _resolve_ytdlp(mpv_exe)
    if ytdlp:
        ytdlp_dir = str(Path(ytdlp).parent)
        env["PATH"] = ytdlp_dir + os.pathsep + env.get("PATH", "")
    return subprocess.Popen(
        args, env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS,
    )
```

In `musichub/cli.py`, update imports at the top:

```python
from .slots import (
    clean_dead_slots, next_slot_id, pipe_for_slot,
    register_slot, unregister_slot, SLOT_PRIMARY,
)
```

Replace `cmd_play` function (lines 154-185):

```python
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

    # Try to reuse existing mpv instance via IPC (replace mode)
    primary_pipe = pipe_for_slot(SLOT_PRIMARY)
    client = MpvIpcClient(primary_pipe, connect_timeout_sec=1.0)
    try:
        client.command(["loadfile", targets[0], "replace"])
        for t in targets[1:]:
            client.command(["loadfile", t, "append"])
        print(json.dumps({"ok": True, "action": "replace", "slot": SLOT_PRIMARY, "targets": targets}))
        return 0
    except MpvIpcError:
        pass  # mpv not running — launch fresh

    # Launch new mpv on slot 0
    proc = launch_mpv(paths, targets, slot_id=SLOT_PRIMARY)
    register_slot(paths, SLOT_PRIMARY, primary_pipe, proc.pid)
    print(f"mpv started (pid={proc.pid})")
    return 0
```

**Step 4: Run tests**

```
python -m pytest tests/test_cmd_play_replace.py tests/test_slots.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add musichub/cli.py musichub/mpv_control.py musichub/slots.py tests/test_cmd_play_replace.py
git commit -m "fix: m play replaces existing mpv instead of spawning duplicate"
```

---

### Task 3: `m layer` — intentional overlay launch

**Files:**
- Modify: `musichub/cli.py` (add `cmd_layer`, register in `build_parser`)

**Context:** `m layer "query"` always starts a NEW mpv instance alongside existing ones. Each gets a unique slot ID and pipe. This is for intentional multi-stream layering (e.g., ambient + focus music).

**Step 1: Write the test**

Create `tests/test_cmd_layer.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_layer


def _args(target="https://youtu.be/abc"):
    ns = argparse.Namespace()
    ns.target = target
    return ns


def test_layer_always_launches_new_process():
    """m layer always spawns a new mpv regardless of existing instances."""
    mock_proc = MagicMock()
    mock_proc.pid = 5678

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.clean_dead_slots", return_value={}), \
         patch("musichub.cli.launch_mpv", return_value=mock_proc) as mock_launch, \
         patch("musichub.cli.register_slot") as mock_register:

        result = cmd_layer(_args())

    assert result == 0
    mock_launch.assert_called_once()
    mock_register.assert_called_once()
    # Should output slot and pid info
```

**Step 2: Run to verify fails**

```
python -m pytest tests/test_cmd_layer.py -v
```

Expected: `ImportError: cannot import name 'cmd_layer'`

**Step 3: Implement**

Add to `musichub/cli.py` after `cmd_play`:

```python
def cmd_layer(args: argparse.Namespace) -> int:
    """Launch a new mpv instance alongside existing ones (overlay mode)."""
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
        print("Usage: m layer <URL or search query>", file=sys.stderr)
        return 1

    # Find next available slot
    registry = clean_dead_slots(paths)
    slot_id = next_slot_id(registry)
    pipe = pipe_for_slot(slot_id)

    proc = launch_mpv(paths, targets, slot_id=slot_id)
    register_slot(paths, slot_id, pipe, proc.pid)
    print(json.dumps({"ok": True, "action": "layer", "slot": slot_id, "pid": proc.pid, "pipe": pipe}))
    return 0
```

Add to `build_parser()` inside `musichub/cli.py`, after the `play` parser block:

```python
p = sub.add_parser("layer", help="Layer a new mpv instance alongside existing ones")
p.add_argument("target", nargs="?", help="URL or search query")
p.set_defaults(func=cmd_layer)
```

**Step 4: Run tests**

```
python -m pytest tests/test_cmd_layer.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add musichub/cli.py tests/test_cmd_layer.py
git commit -m "feat: add m layer command for intentional multi-instance overlay"
```

---

### Task 4: `m vol <slot> <level>` — per-slot volume control

**Files:**
- Modify: `musichub/cli.py` (add `cmd_vol`, register in `build_parser`)

**Context:** Each mpv slot has independent volume. `m vol 0 70` sets slot 0 to 70%. `m vol all 50` sets all active slots to 50%. Volume range is 0–130 (mpv's native range; 100 = normal).

**Step 1: Write the test**

Create `tests/test_cmd_vol.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_vol
from musichub.slots import SlotInfo


def _args(slot="0", level=70):
    ns = argparse.Namespace()
    ns.slot = slot
    ns.level = level
    return ns


def test_vol_sets_volume_on_slot():
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value={
             "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)
         }), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client):

        result = cmd_vol(_args("0", 70))

    assert result == 0
    mock_client.command.assert_called_with(["set_property", "volume", 70])


def test_vol_all_sets_all_slots():
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}

    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 5678),
    }

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client):

        result = cmd_vol(_args("all", 50))

    assert result == 0
    # Called twice, once per slot
    assert mock_client.command.call_count == 2


def test_vol_invalid_slot_returns_error():
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry):

        result = cmd_vol(_args("5", 70))  # slot 5 doesn't exist

    assert result == 1
```

**Step 2: Run to verify fails**

```
python -m pytest tests/test_cmd_vol.py -v
```

Expected: `ImportError: cannot import name 'cmd_vol'`

**Step 3: Implement**

Add to `musichub/cli.py`:

```python
def cmd_vol(args: argparse.Namespace) -> int:
    """Set volume on a specific slot or all slots."""
    paths = get_paths()
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
            active = list(registry.keys())
            print(f"Slot {args.slot!r} not found. Active slots: {active}", file=sys.stderr)
            return 1
        slots_to_update = [info]

    results = []
    for info in slots_to_update:
        client = MpvIpcClient(info.pipe)
        try:
            client.command(["set_property", "volume", level])
            results.append({"slot": info.slot_id, "volume": level, "ok": True})
        except MpvIpcError as exc:
            results.append({"slot": info.slot_id, "error": str(exc), "ok": False})

    print(json.dumps(results, ensure_ascii=False))
    return 0
```

Add to `build_parser()` after `pause`:

```python
p = sub.add_parser("vol", help="Set volume for a slot (0-130, 100=normal)")
p.add_argument("slot", nargs="?", default="0", help="Slot ID or 'all'")
p.add_argument("level", type=int, help="Volume level 0-130")
p.set_defaults(func=cmd_vol)
```

**Step 4: Run tests**

```
python -m pytest tests/test_cmd_vol.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add musichub/cli.py tests/test_cmd_vol.py
git commit -m "feat: add m vol command for per-slot volume control"
```

---

### Task 5: `m slots` — list active instances

**Files:**
- Modify: `musichub/cli.py` (add `cmd_slots`, register in `build_parser`)

**Context:** Shows all active mpv slots with their slot IDs, pipes, PIDs, and current track (best-effort IPC query).

**Step 1: Write the test**

Create `tests/test_cmd_slots.py`:

```python
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_slots
from musichub.slots import SlotInfo


def test_slots_lists_active():
    mock_client = MagicMock()
    mock_client.get_property.side_effect = lambda prop: {
        "media-title": "Test Song",
        "volume": 100,
    }.get(prop)

    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("builtins.print") as mock_print:

        result = cmd_slots(argparse.Namespace())

    assert result == 0
    output = json.loads(mock_print.call_args[0][0])
    assert output[0]["slot"] == "0"
    assert output[0]["pid"] == 1234


def test_slots_empty():
    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value={}), \
         patch("builtins.print") as mock_print:

        result = cmd_slots(argparse.Namespace())

    assert result == 0
    output = json.loads(mock_print.call_args[0][0])
    assert output == []
```

**Step 2: Run to verify fails**

```
python -m pytest tests/test_cmd_slots.py -v
```

**Step 3: Implement**

Add to `musichub/cli.py`:

```python
def cmd_slots(_args: argparse.Namespace) -> int:
    """List all active mpv slots with current track info."""
    paths = get_paths()
    registry = clean_dead_slots(paths)

    results = []
    for slot_id, info in sorted(registry.items()):
        entry: dict = {"slot": slot_id, "pid": info.pid, "pipe": info.pipe}
        # Best-effort: query current track
        client = MpvIpcClient(info.pipe, connect_timeout_sec=1.0)
        try:
            entry["title"] = client.get_property("media-title")
            entry["volume"] = client.get_property("volume")
        except MpvIpcError:
            entry["title"] = None
            entry["volume"] = None
        results.append(entry)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0
```

Add to `build_parser()`:

```python
p = sub.add_parser("slots", help="List active mpv instances")
p.set_defaults(func=cmd_slots)
```

**Step 4: Run tests**

```
python -m pytest tests/test_cmd_slots.py -v
```

**Step 5: Commit**

```bash
git add musichub/cli.py tests/test_cmd_slots.py
git commit -m "feat: add m slots command to list active mpv instances"
```

---

### Task 6: Extend `m stop` to support slot targeting

**Files:**
- Modify: `musichub/cli.py` (`cmd_stop` function and its parser entry)

**Context:** `m stop` should keep working as before (stops slot 0). But now also support `m stop 1` (stop specific slot) and `m stop all` (stop everything). After stopping, unregister from slots registry.

**Step 1: Write the test**

Create `tests/test_cmd_stop.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_stop
from musichub.slots import SlotInfo


def _args(slot=None):
    ns = argparse.Namespace()
    ns.slot = slot
    return ns


def test_stop_default_stops_slot_0():
    mock_client = MagicMock()
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.unregister_slot") as mock_unreg:

        result = cmd_stop(_args(slot=None))

    assert result == 0
    mock_client.command.assert_called_with(["quit"])
    mock_unreg.assert_called_once()


def test_stop_all_stops_all_slots():
    mock_client = MagicMock()
    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 5678),
    }

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.unregister_slot") as mock_unreg:

        result = cmd_stop(_args(slot="all"))

    assert result == 0
    assert mock_client.command.call_count == 2
    assert mock_unreg.call_count == 2
```

**Step 2: Run to verify fails**

```
python -m pytest tests/test_cmd_stop.py -v
```

**Step 3: Implement**

Replace `cmd_stop` in `musichub/cli.py`:

```python
def cmd_stop(args: argparse.Namespace) -> int:
    """Stop specific slot or all slots. Defaults to slot 0."""
    paths = get_paths()
    registry = clean_dead_slots(paths)
    slot_arg = getattr(args, "slot", None)

    if slot_arg == "all":
        slots_to_stop = list(registry.values())
    else:
        target = slot_arg or SLOT_PRIMARY
        info = registry.get(target)
        if info is None:
            # Fall back to primary pipe even if not in registry (backward compat)
            from .slots import pipe_for_slot
            client = MpvIpcClient(pipe_for_slot(SLOT_PRIMARY))
            try:
                client.command(["quit"])
            except MpvIpcError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps({"ok": True, "action": "stop", "slot": SLOT_PRIMARY}))
            return 0
        slots_to_stop = [info]

    results = []
    for info in slots_to_stop:
        client = MpvIpcClient(info.pipe)
        try:
            client.command(["quit"])
            unregister_slot(paths, info.slot_id)
            results.append({"slot": info.slot_id, "ok": True})
        except MpvIpcError as exc:
            unregister_slot(paths, info.slot_id)  # clean up registry anyway
            results.append({"slot": info.slot_id, "ok": False, "error": str(exc)})

    print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False))
    return 0
```

Update `stop` parser in `build_parser()`:

```python
p = sub.add_parser("stop", help="Stop playback (optionally specify slot or 'all')")
p.add_argument("slot", nargs="?", default=None, help="Slot ID, 'all', or omit for slot 0")
p.set_defaults(func=cmd_stop)
```

**Step 4: Run tests**

```
python -m pytest tests/test_cmd_stop.py -v
```

**Step 5: Commit**

```bash
git add musichub/cli.py tests/test_cmd_stop.py
git commit -m "feat: extend m stop to support slot targeting and multi-slot teardown"
```

---

### Task 7: NL patterns for new commands

**Files:**
- Modify: `musichub/nl.py`

**Context:** Add `layer`, `vol`, `slots` to `KNOWN_COMMANDS`. Add freeform patterns for each so Chinese/English natural language routes correctly.

**Step 1: Write the test**

Add to a new file `tests/test_nl_new_cmds.py`:

```python
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.nl import parse_freeform


def test_layer_english():
    r = parse_freeform("layer some ambient music")
    assert r and r.argv[0] == "layer"
    assert "ambient" in r.argv[1]


def test_layer_chinese():
    r = parse_freeform("叠加播放白噪声")
    assert r and r.argv[0] == "layer"


def test_vol_slot_level():
    r = parse_freeform("vol 0 70")
    assert r and r.argv == ["vol", "0", "70"]


def test_vol_chinese_pattern():
    r = parse_freeform("把第0个音量调到80")
    assert r and r.argv[0] == "vol"
    assert "80" in r.argv


def test_slots_list():
    r = parse_freeform("显示所有播放器")
    assert r and r.argv == ["slots"]


def test_stop_all_chinese():
    r = parse_freeform("全部停止")
    assert r and r.argv == ["stop", "all"]
```

**Step 2: Run to verify fails**

```
python -m pytest tests/test_nl_new_cmds.py -v
```

**Step 3: Implement**

In `musichub/nl.py`:

1. Add to `KNOWN_COMMANDS` set:
```python
"layer",
"vol",
"slots",
```

2. Add rules in `parse_freeform()`. Insert after the existing `stop/pause` block:

```python
# Layer / overlay
if any(k in lower for k in ["叠加播放", "同时播放", "layered", "overlay"]):
    rest = text
    for prefix in ["叠加播放", "同时播放"]:
        if text.startswith(prefix):
            rest = text[len(prefix):].strip()
            break
    return ParsedIntent(["layer", rest] if rest else ["layer"], "layer overlay playback")
if lower.startswith("layer "):
    return ParsedIntent(["layer", text[6:].strip()], "layer overlay playback")

# Volume control: "vol 0 70" or "把第0个音量调到80"
vol_match = re.search(r"(?:vol\s+|音量.*?)(\d+|all)\s+(\d+)", lower)
if vol_match:
    return ParsedIntent(["vol", vol_match.group(1), vol_match.group(2)], "volume control")

# Slots list
if any(k in lower for k in ["查看槽位", "所有播放器", "所有slot", "slots", "list slots"]):
    return ParsedIntent(["slots"], "list active slots")

# Stop all
if any(k in lower for k in ["全部停止", "停止所有", "stop all", "全停"]):
    return ParsedIntent(["stop", "all"], "stop all slots")
```

**Step 4: Run tests**

```
python -m pytest tests/test_nl_new_cmds.py -v
```

Note: Some NL tests may need minor pattern tweaks — adjust regex or keywords to match test assertions. That's fine.

**Step 5: Commit**

```bash
git add musichub/nl.py tests/test_nl_new_cmds.py
git commit -m "feat: add NL patterns for layer, vol, slots, stop all"
```

---

### Task 8: Update AGENTS.md

**Files:**
- Modify: `AGENTS.md`

**Context:** AI agents need to know about the new commands. Update the command reference table and decision guide.

**Step 1: No test needed** (documentation only)

**Step 2: Update AGENTS.md**

Add to the command reference table:

```markdown
| `m layer "<query>"` | Start a new mpv instance alongside existing (overlay) | `m layer "白噪音"` |
| `m vol <slot> <level>` | Set volume for a slot (0-130, 100=normal) | `m vol 0 70` |
| `m vol all <level>` | Set volume for all active slots | `m vol all 60` |
| `m slots` | List all active mpv instances with current track | `m slots` |
| `m stop [slot]` | Stop a specific slot (default: 0) or all | `m stop all` |
```

Add to the Decision guide:

```
User wants to play music alongside current music (overlay/layer)?
  → m layer "<query>"

User wants to adjust volume of a specific stream?
  → m vol <slot> <level>

User wants to see all active streams?
  → m slots

User wants to stop everything?
  → m stop all
```

**Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md with layer/vol/slots commands"
```

---

### Task 9: Run full test suite + manual smoke test

**Step 1: Run all tests**

```
cd C:\Users\mzmat\music-hub
python -m pytest tests/ -v
```

Expected: All tests green.

**Step 2: Manual smoke test**

```powershell
# Start primary playback
m 播放 许巍

# Verify it replaces (not duplicates) when run again
m 播放 周杰伦 稻香

# Add overlay
m layer "white noise ambient"

# Check active slots
m slots

# Adjust volumes
m vol 0 70
m vol 1 40

# Stop overlay only
m stop 1

# Stop all
m stop all
```

**Step 3: Push to GitHub**

```bash
git push origin main
```
