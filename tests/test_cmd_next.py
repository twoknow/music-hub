import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import cmd_next
from musichub.mpv_ipc import MpvIpcError


def _args(slot="0"):
    ns = argparse.Namespace()
    ns.slot = slot
    return ns


def test_next_refills_when_queue_is_exhausted():
    mock_client = MagicMock()
    mock_conn = MagicMock()
    mock_paths = MagicMock()
    mock_paths.db_path = "dummy.db"
    snap = {
        "path": "https://youtu.be/current",
        "playback_time": 10.0,
        "duration": 120.0,
        "playlist_pos": 0,
        "playlist_count": 1,
        "metadata": {},
    }

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli._resolve_slot_pipe", return_value=("0", r"\\.\pipe\musichub-mpv")), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli._get_mpv_snapshot", return_value=snap), \
         patch("musichub.cli.db.connect", return_value=mock_conn), \
         patch("musichub.cli._upsert_from_snapshot", return_value=(1, snap["path"], "youtube")), \
         patch("musichub.cli.db.record_play_event"), \
         patch("musichub.cli._append_recommendations_to_slot", return_value=2) as mock_append, \
         patch("builtins.print") as mock_print:

        result = cmd_next(_args())

    assert result == 0
    mock_append.assert_called_once()
    mock_client.command.assert_called_with(["playlist-next", "force"])
    output = json.loads(mock_print.call_args[0][0])
    assert output["ok"] is True
    assert output["appended"] == 2


def test_next_recovers_when_pipe_missing():
    mock_client = MagicMock()
    mock_paths = MagicMock()

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli._resolve_slot_pipe", return_value=("0", r"\\.\pipe\musichub-mpv")), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli._get_mpv_snapshot", side_effect=MpvIpcError("pipe missing")), \
         patch("musichub.cli._recover_next_playback", return_value=(True, "https://youtu.be/recovered")), \
         patch("builtins.print") as mock_print:

        result = cmd_next(_args())

    assert result == 0
    output = json.loads(mock_print.call_args[0][0])
    assert output["ok"] is True
    assert output["recovered"] is True


def test_next_returns_error_when_recovery_fails():
    mock_client = MagicMock()
    mock_paths = MagicMock()

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli._resolve_slot_pipe", return_value=("0", r"\\.\pipe\musichub-mpv")), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client), \
         patch("musichub.cli._get_mpv_snapshot", side_effect=MpvIpcError("pipe missing")), \
         patch("musichub.cli._recover_next_playback", return_value=(False, None)):

        result = cmd_next(_args())

    assert result == 1
