import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.cli import _snapshot_mpv_slot


def test_snapshot_returns_empty_without_active_slot():
    with patch("musichub.cli.active_slot_info", return_value=None), patch("musichub.cli.db.connect") as mock_connect:
        snap = _snapshot_mpv_slot(object(), "0")

    assert snap == {}
    mock_connect.assert_not_called()
