import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_slots
from musichub.slots import SlotInfo
from musichub.mpv_ipc import MpvIpcError


def test_slots_lists_active():
    mock_client = MagicMock()
    mock_client.get_property.side_effect = lambda prop: {
        "media-title": "Test Song",
        "volume": 100,
    }.get(prop)

    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("builtins.print") as mock_print:

        result = cmd_slots(argparse.Namespace())

    assert result == 0
    output = json.loads(mock_print.call_args[0][0])
    assert output[0]["slot"] == "0"
    assert output[0]["pid"] == 1234
    assert output[0]["title"] == "Test Song"


def test_slots_empty():
    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value={}), \
         patch("builtins.print") as mock_print:

        result = cmd_slots(argparse.Namespace())

    assert result == 0
    output = json.loads(mock_print.call_args[0][0])
    assert output == []


def test_slots_ipc_failure_shows_nulls():
    mock_client = MagicMock()
    mock_client.get_property.side_effect = MpvIpcError("dead")

    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("builtins.print") as mock_print:

        result = cmd_slots(argparse.Namespace())

    assert result == 0
    output = json.loads(mock_print.call_args[0][0])
    assert output[0]["title"] is None
    assert output[0]["volume"] is None
