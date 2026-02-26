import json
import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.slots import (
    pipe_for_slot, next_slot_id, SlotInfo,
    load_registry, save_registry, clean_dead_slots,
    register_slot, unregister_slot, SLOT_PRIMARY,
)


def make_paths(tmp_path):
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
    register_slot(paths, "0", r"\\.\pipe\musichub-mpv", 99999999)
    register_slot(paths, "1", r"\\.\pipe\musichub-mpv-1", 99999998)

    alive = clean_dead_slots(paths)
    assert "0" not in alive
    assert "1" not in alive


def test_clean_dead_slots_keeps_current_process(tmp_path):
    paths = make_paths(tmp_path)
    my_pid = os.getpid()
    register_slot(paths, "0", r"\\.\pipe\musichub-mpv", my_pid)

    alive = clean_dead_slots(paths)
    assert "0" in alive
