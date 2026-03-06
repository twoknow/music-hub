import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_af
from musichub.playback_prefs import PlaybackPrefs
from musichub.slots import SlotInfo


def _args(state="status"):
    ns = argparse.Namespace()
    ns.state = state
    return ns


def test_af_off_persists_and_applies_to_active_slots():
    mock_paths = MagicMock()
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}
    mock_client.get_property.return_value = []

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli.load_playback_prefs", return_value=PlaybackPrefs(loudnorm_enabled=True)), \
         patch("musichub.cli.save_playback_prefs") as mock_save, \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("builtins.print") as mock_print:

        result = cmd_af(_args("off"))

    assert result == 0
    mock_save.assert_called_once_with(mock_paths, PlaybackPrefs(loudnorm_enabled=False))
    mock_client.command.assert_called_once_with(["set_property", "af", []])
    payload = json.loads(mock_print.call_args[0][0])
    assert payload["loudnorm_enabled"] is False
    assert payload["results"][0]["ok"] is True


def test_af_status_reports_stored_and_live_state():
    mock_paths = MagicMock()
    registry = {"0": SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)}
    mock_client = MagicMock()
    mock_client.get_property.return_value = [{"name": "loudnorm", "enabled": True, "params": {}}]

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli.load_playback_prefs", return_value=PlaybackPrefs(loudnorm_enabled=False)), \
         patch("musichub.cli.clean_dead_slots", return_value=registry), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("builtins.print") as mock_print:

        result = cmd_af(_args("status"))

    assert result == 0
    payload = json.loads(mock_print.call_args[0][0])
    assert payload["action"] == "status"
    assert payload["loudnorm_enabled"] is False
    assert payload["results"][0]["loudnorm_enabled"] is True
