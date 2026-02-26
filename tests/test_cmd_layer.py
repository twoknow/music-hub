import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_layer
from musichub.slots import SlotInfo


def _args(target="https://youtu.be/abc"):
    ns = argparse.Namespace()
    ns.target = target
    return ns


def test_layer_always_launches_new_process():
    """m layer spawns a new mpv alongside existing instances."""
    mock_proc = MagicMock()
    mock_proc.pid = 5678
    existing = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.clean_dead_slots", return_value=existing), \
         patch("musichub.cli.launch_mpv", return_value=mock_proc) as mock_launch, \
         patch("musichub.cli.register_slot") as mock_register:

        result = cmd_layer(_args())

    assert result == 0
    mock_launch.assert_called_once()
    mock_register.assert_called_once()


def test_layer_requires_existing_playback():
    """m layer returns error if nothing is playing (empty registry)."""
    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.clean_dead_slots", return_value={}):

        result = cmd_layer(_args())

    assert result == 1


def test_layer_uses_next_available_slot():
    """When slot 0 is occupied, layer uses slot 1."""
    mock_proc = MagicMock()
    mock_proc.pid = 5678
    existing = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.clean_dead_slots", return_value=existing), \
         patch("musichub.cli.launch_mpv", return_value=mock_proc) as mock_launch, \
         patch("musichub.cli.register_slot") as mock_register:

        result = cmd_layer(_args())

    assert result == 0
    # Should use slot "1"
    call_kwargs = mock_launch.call_args
    assert call_kwargs[1]["slot_id"] == "1" or call_kwargs[0][2] == "1"
    mock_register.assert_called_once()


def test_layer_no_target_returns_error():
    """m layer without target prints usage and returns 1."""
    ns = argparse.Namespace()
    ns.target = None

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"):
        result = cmd_layer(ns)

    assert result == 1


def test_layer_outputs_slot_info():
    """m layer outputs JSON with slot, pid, pipe."""
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    existing = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.clean_dead_slots", return_value=existing), \
         patch("musichub.cli.launch_mpv", return_value=mock_proc), \
         patch("musichub.cli.register_slot"), \
         patch("builtins.print") as mock_print:

        result = cmd_layer(_args())

    assert result == 0
    # Find the JSON print call (last call to print)
    json_output = None
    for call in mock_print.call_args_list:
        try:
            json_output = json.loads(call[0][0])
            break
        except (json.JSONDecodeError, IndexError):
            continue

    assert json_output is not None
    assert json_output["action"] == "layer"
    assert json_output["slot"] == "1"
    assert json_output["pid"] == 9999
