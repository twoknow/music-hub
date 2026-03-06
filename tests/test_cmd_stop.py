import sys
import json
from pathlib import Path
from unittest.mock import ANY, patch
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_stop
from musichub.slots import SlotInfo


def _args(slot=None):
    ns = argparse.Namespace()
    ns.slot = slot
    return ns


def test_stop_default_stops_slot_0():
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli._stop_slot_instance", return_value=True) as mock_stop:

        result = cmd_stop(_args(slot=None))

    assert result == 0
    mock_stop.assert_called_once_with(ANY, "0", registry["0"])


def test_stop_all_stops_all_slots():
    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 5678),
    }

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli._stop_slot_instance", return_value=True) as mock_stop, \
         patch("musichub.cli._stop_profile_orphans", return_value=[]) as mock_orphans:

        result = cmd_stop(_args(slot="all"))

    assert result == 0
    assert mock_stop.call_count == 2
    mock_orphans.assert_called_once()


def test_stop_specific_slot():
    registry = {
        "0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234),
        "1": SlotInfo("1", r"\\.\pipe\musichub-mpv-1", 5678),
    }

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli._stop_slot_instance", return_value=True) as mock_stop:

        result = cmd_stop(_args(slot="1"))

    assert result == 0
    mock_stop.assert_called_once_with(ANY, "1", registry["1"])


def test_stop_all_kills_profile_orphans_when_registry_empty():
    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli.clean_dead_slots", return_value={}), \
         patch("musichub.cli._stop_profile_orphans", return_value=[{"slot": "orphan", "pid": 7777, "ok": True}]) as mock_orphans, \
         patch("builtins.print") as mock_print:

        result = cmd_stop(_args(slot="all"))

    assert result == 0
    mock_orphans.assert_called_once()
    payload = json.loads(mock_print.call_args[0][0])
    assert payload["results"] == [{"slot": "orphan", "pid": 7777, "ok": True}]
