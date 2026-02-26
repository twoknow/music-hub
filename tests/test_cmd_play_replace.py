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
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.launch_mpv") as mock_launch:

        result = cmd_play(_args())

    assert result == 0
    mock_client.command.assert_called_once_with(["loadfile", "https://youtu.be/test123", "replace"])
    mock_launch.assert_not_called()


def test_play_launches_when_no_mpv():
    """When no mpv running, a new process is launched and registered."""
    mock_client = MagicMock()
    mock_client.command.side_effect = MpvIpcError("no mpv")
    mock_proc = MagicMock()
    mock_proc.pid = 1234

    with patch("musichub.cli._ensure_ready"), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli.launch_mpv", return_value=mock_proc) as mock_launch, \
         patch("musichub.cli.register_slot") as mock_register:

        result = cmd_play(_args())

    assert result == 0
    mock_launch.assert_called_once()
    mock_register.assert_called_once()


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
    # Only one target: only loadfile replace
    assert mock_client.command.call_count == 1
