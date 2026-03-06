import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import _snapshot_mpv_slot
from musichub.mpv_ipc import MpvIpcError
from musichub.slots import SlotInfo


def test_snapshot_returns_empty_without_active_slot():
    with patch("musichub.cli.active_slot_info", return_value=None), patch("musichub.cli.db.connect") as mock_connect:
        snap = _snapshot_mpv_slot(object(), "0")

    assert snap == {}
    mock_connect.assert_not_called()


def test_snapshot_tolerates_unavailable_optional_properties():
    mock_client = MagicMock()

    def get_property(name: str):
        values = {
            "path": "https://www.youtube.com/watch?v=VM8DHYeCvSE",
            "media-title": "Focus Mix",
            "duration": 120.0,
            "time-pos": 12.5,
            "playlist-pos": 0,
            "playlist-count": 1,
            "metadata": {"artist": "Tester"},
        }
        if name in {"chapter", "chapter-metadata"}:
            raise MpvIpcError(f"{name} unavailable")
        return values[name]

    mock_client.get_property.side_effect = get_property

    with patch("musichub.cli.active_slot_info", return_value=SlotInfo("0", r"\\.\pipe\musichub-mpv", 1234)), \
         patch("musichub.cli.MpvIpcClient", return_value=mock_client):
        snap = _snapshot_mpv_slot(object(), "0")

    assert snap["path"] == "https://www.youtube.com/watch?v=VM8DHYeCvSE"
    assert snap["chapter"] is None
    assert snap["chapter_metadata"] is None
    assert snap["playlist_count"] == 1
