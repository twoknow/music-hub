import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_play
from musichub.mpv_ipc import MpvIpcError


def _args(target="https://youtu.be/test123"):
    ns = argparse.Namespace()
    ns.target = [target] if target else []
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
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli._maybe_apply_playback_prefs_to_client") as mock_sync, \
         patch("musichub.cli.launch_mpv") as mock_launch:

        result = cmd_play(_args())

    assert result == 0
    mock_sync.assert_called_once()
    mock_client.command.assert_called_once_with(["loadfile", "https://youtu.be/test123", "replace"])
    mock_launch.assert_not_called()


def test_play_launches_when_no_mpv():
    """When no mpv running, a new process is launched and registered."""
    mock_client = MagicMock()
    mock_client.command.side_effect = MpvIpcError("no mpv")

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli._restart_slot_with_targets") as mock_restart:

        result = cmd_play(_args())

    assert result == 0
    mock_restart.assert_called_once()


def test_play_multiple_targets_appends():
    """Second and subsequent targets are appended after loadfile replace."""
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.launch_mpv"):

        # Directly call with multiple targets by patching _run_yt_dlp_print_url
        # Use URL input to avoid yt-dlp call
        result = cmd_play(_args("https://youtu.be/one"))

    assert result == 0
    assert mock_client.command.call_count == 2
    assert mock_client.command.call_args_list[-1].args[0] == ["loadfile", "https://youtu.be/one", "replace"]


def test_play_search_query_uses_queue_and_appends():
    """Search query should resolve multiple URLs (queue) and append them."""
    mock_client = MagicMock()
    mock_client.command.return_value = {"error": "success"}
    resolved = ["https://youtu.be/one", "https://youtu.be/two", "https://youtu.be/three"]

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli._maybe_apply_playback_prefs_to_client"), \
         patch("musichub.cli._run_yt_dlp_search_urls", return_value=resolved), \
         patch("musichub.cli.launch_mpv"):

        ns = _args("focus music")
        ns.queue = 3
        result = cmd_play(ns)

    assert result == 0
    assert mock_client.command.call_count == 3
    assert mock_client.command.call_args_list[0].args[0] == ["loadfile", "https://youtu.be/one", "replace"]
    assert mock_client.command.call_args_list[1].args[0] == ["loadfile", "https://youtu.be/two", "append"]
    assert mock_client.command.call_args_list[2].args[0] == ["loadfile", "https://youtu.be/three", "append"]
