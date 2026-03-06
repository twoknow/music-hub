import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.mpv_control import launch_mpv
from musichub.playback_prefs import PlaybackPrefs


def _paths():
    mock_paths = MagicMock()
    mock_paths.mpv_pipe = r"\\.\pipe\musichub-mpv-test"
    mock_paths.mpv_script = Path("C:/tmp/musichub.lua")
    mock_paths.events_jsonl = Path("C:/tmp/mpv_events.jsonl")
    return mock_paths


def test_launch_mpv_omits_loudnorm_by_default():
    mock_proc = MagicMock()

    with patch("musichub.mpv_control.ensure_dirs"), \
         patch("musichub.mpv_control.resolve_mpv_exe", return_value="C:/tools/mpv.exe"), \
         patch("musichub.mpv_control._resolve_ytdlp", return_value=None), \
         patch("musichub.mpv_control.load_playback_prefs", return_value=PlaybackPrefs(loudnorm_enabled=False)), \
         patch("musichub.mpv_control.subprocess.Popen", return_value=mock_proc) as mock_popen:

        launch_mpv(_paths(), ["https://youtu.be/test"])

    args = mock_popen.call_args.args[0]
    assert "--af=loudnorm" not in args


def test_launch_mpv_includes_loudnorm_when_enabled():
    mock_proc = MagicMock()

    with patch("musichub.mpv_control.ensure_dirs"), \
         patch("musichub.mpv_control.resolve_mpv_exe", return_value="C:/tools/mpv.exe"), \
         patch("musichub.mpv_control._resolve_ytdlp", return_value=None), \
         patch("musichub.mpv_control.load_playback_prefs", return_value=PlaybackPrefs(loudnorm_enabled=True)), \
         patch("musichub.mpv_control.subprocess.Popen", return_value=mock_proc) as mock_popen:

        launch_mpv(_paths(), ["https://youtu.be/test"])

    args = mock_popen.call_args.args[0]
    assert "--af=loudnorm" in args
