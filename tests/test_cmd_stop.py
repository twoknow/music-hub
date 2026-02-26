import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_stop
from musichub.slots import SlotInfo
from musichub.mpv_ipc import MpvIpcError


def _args(slot=None):
    ns = argparse.Namespace()
    ns.slot = slot
    return ns


def test_stop_default_stops_slot_0():
    mock_client = MagicMock()
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.unregister_slot") as mock_unreg:

        result = cmd_stop(_args(slot=None))

    assert result == 0
    mock_client.command.assert_called_once_with(["quit"])
    mock_unreg.assert_called_once()


def test_stop_all_stops_all_slots():
    mock_client = MagicMock()
    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 5678),
    }

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.unregister_slot") as mock_unreg:

        result = cmd_stop(_args(slot="all"))

    assert result == 0
    assert mock_client.command.call_count == 2
    assert mock_unreg.call_count == 2


def test_stop_specific_slot():
    mock_client = MagicMock()
    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 5678),
    }

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.unregister_slot") as mock_unreg:

        result = cmd_stop(_args(slot="1"))

    assert result == 0
    assert mock_client.command.call_count == 1
    mock_unreg.assert_called_once()
