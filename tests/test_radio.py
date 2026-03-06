import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import _canonical_youtube_watch_url, _extract_youtube_video_id, cmd_radio


def _args(limit=3):
    ns = argparse.Namespace()
    ns.limit = limit
    return ns


def test_extract_youtube_video_id_rejects_dummy_import_url():
    assert _extract_youtube_video_id("https://music.youtube.com/watch?v=ytm123") is None
    assert _canonical_youtube_watch_url("https://music.youtube.com/watch?v=83zDU4of-co") == (
        "https://www.youtube.com/watch?v=83zDU4of-co"
    )


def test_radio_falls_back_to_search_when_related_missing_for_current_track():
    mock_paths = MagicMock()
    snap = {
        "path": "https://www.youtube.com/watch?v=83zDU4of-co",
        "media_title": "Test Song",
        "metadata": {"artist": "Test Artist"},
    }

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli._snapshot_mpv_slot", return_value=snap), \
         patch("musichub.cli._get_yt_related_urls", return_value=[]), \
         patch("musichub.cli._radio_search_fallback", return_value=["https://youtu.be/abcdefghijk"]) as mock_fallback, \
         patch("musichub.cli.active_slot_info", return_value=None), \
         patch("musichub.cli.MpvIpcClient"), \
         patch("musichub.cli._load_targets_into_client") as mock_load, \
         patch("builtins.print") as mock_print:

        result = cmd_radio(_args())

    assert result == 0
    mock_fallback.assert_called_once_with("Test Artist Test Song", limit=3, exclude_url=snap["path"])
    mock_load.assert_called_once()
    payload = json.loads(mock_print.call_args_list[-1][0][0])
    assert payload["ok"] is True
    assert payload["targets"] == ["https://youtu.be/abcdefghijk"]


def test_radio_uses_search_seed_when_good_history_url_is_invalid():
    mock_paths = MagicMock()
    mock_ctx = MagicMock()
    mock_conn = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn
    mock_ctx.__exit__.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = [
        {
            "source_url": "https://music.youtube.com/watch?v=ytm123",
            "title": "Imported Song",
            "artist": "Imported Artist",
        }
    ]

    with patch("musichub.cli._ensure_ready", return_value=mock_paths), \
         patch("musichub.cli._safe_sync_events"), \
         patch("musichub.cli._snapshot_mpv_slot", return_value={}), \
         patch("musichub.cli.db.connect", return_value=mock_ctx), \
         patch("musichub.cli.recommend", return_value=[]), \
         patch("musichub.cli._radio_search_fallback", return_value=["https://youtu.be/abcdefghijk"]) as mock_fallback, \
         patch("musichub.cli.active_slot_info", return_value=None), \
         patch("musichub.cli.MpvIpcClient"), \
         patch("musichub.cli._load_targets_into_client") as mock_load, \
         patch("builtins.print") as mock_print:

        result = cmd_radio(_args(limit=1))

    assert result == 0
    mock_fallback.assert_called_once_with("Imported Artist Imported Song", limit=1, exclude_url=None)
    mock_load.assert_called_once()
    payload = json.loads(mock_print.call_args_list[-1][0][0])
    assert payload["ok"] is True
    assert payload["targets"] == ["https://youtu.be/abcdefghijk"]
