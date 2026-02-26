import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_vol
from musichub.slots import SlotInfo
from musichub.mpv_ipc import MpvIpcError


def _args(slot="0", level=70):
    ns = argparse.Namespace()
    ns.slot = slot
    ns.level = level
    return ns


def test_vol_sets_volume_on_slot():
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}

    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client):

        result = cmd_vol(_args("0", 70))

    assert result == 0
    mock_client.command.assert_called_once_with(["set_property", "volume", 70])


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
    assert mock_client.command.call_count == 2


def test_vol_invalid_slot_returns_error():
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry):

        result = cmd_vol(_args("5", 70))

    assert result == 1


def test_vol_no_active_slots_returns_error():
    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value={}):

        result = cmd_vol(_args("0", 70))

    assert result == 1


def test_vol_clamps_level():
    """Volume above 130 is clamped to 130, below 0 clamped to 0."""
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}

    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client):

        cmd_vol(_args("0", 200))  # above max

    mock_client.command.assert_called_once_with(["set_property", "volume", 130])


def test_vol_ipc_error_returns_ok_false():
    """IPC failure per slot is reported but does not crash."""
    mock_client = MagicMock()
    mock_client.command.side_effect = MpvIpcError("pipe dead")

    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli.get_paths"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("builtins.print") as mock_print:

        result = cmd_vol(_args("0", 70))

    assert result == 0  # overall command succeeds
    output = json.loads(mock_print.call_args[0][0])
    assert output[0]["ok"] is False
