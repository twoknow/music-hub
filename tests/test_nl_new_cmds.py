import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub.nl import parse_freeform


def test_layer_english():
    r = parse_freeform("layer ambient music")
    assert r and r.argv[0] == "layer"
    assert "ambient" in r.argv[1]


def test_layer_chinese():
    r = parse_freeform("叠加播放白噪声")
    assert r and r.argv[0] == "layer"
    assert "白噪声" in r.argv[1]


def test_vol_slot_level():
    r = parse_freeform("vol 0 70")
    assert r and r.argv == ["vol", "0", "70"]


def test_slots_list():
    r = parse_freeform("显示所有播放器")
    assert r and r.argv == ["slots"]


def test_stop_all_chinese():
    r = parse_freeform("全部停止")
    assert r and r.argv == ["stop", "all"]


def test_stop_all_english():
    r = parse_freeform("stop all")
    assert r and r.argv == ["stop", "all"]


def test_undo_natural_language():
    r = parse_freeform("撤销上一步")
    assert r and r.argv == ["undo"]


def test_session_save_natural_language():
    r = parse_freeform("保存会话 工作流")
    assert r and r.argv[:2] == ["session", "save"]
    assert "工作流" in r.argv[-1]


def test_commands_help_natural_language():
    r = parse_freeform("怎么用")
    assert r and r.argv == ["commands"]


def test_restore_backup_without_zip_goes_to_commands():
    r = parse_freeform("恢复备份")
    assert r and r.argv == ["commands"]
