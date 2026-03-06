from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass
class ParsedIntent:
    argv: list[str]
    reason: str


KNOWN_COMMANDS = {
    "init",
    "sync-events",
    "rec",
    "stats",
    "play",
    "current",
    "stop",
    "pause",
    "good",
    "bad",
    "next",
    "sync",
    "daemon",
    "ask",
    "doctor",
    "train",
    "layer",
    "vol",
    "af",
    "slots",
    "undo",
    "session",
    "export",
    "import",
    "commands",
    "radio",
    "note",
    "journal",
}


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _extract_after_prefix(text: str, prefixes: list[str]) -> str | None:
    for p in prefixes:
        if text.startswith(p):
            return text[len(p) :].strip()
    return None


def parse_freeform(raw: str) -> ParsedIntent | None:
    text = _strip_quotes(raw).strip()
    if not text:
        return None

    lower = text.casefold()

    # Explicit shell-like command passthrough: /play xxx or :play xxx
    if text.startswith("/") or text.startswith(":"):
        parts = shlex.split(text[1:])
        if parts:
            return ParsedIntent(parts, "explicit command prefix")

    if any(k in lower for k in ["命令", "帮助", "help", "how to use", "怎么用", "usage", "cheatsheet"]):
        return ParsedIntent(["commands"], "command cheatsheet request")

    if any(k in lower for k in ["撤销", "undo", "回退上一步", "取消上一步"]):
        return ParsedIntent(["undo"], "undo last action")

    if any(k in lower for k in ["保存会话", "save session"]):
        name = _extract_after_prefix(text, ["保存会话", "save session", "session save"])
        return ParsedIntent(["session", "save", name] if name else ["session", "save"], "save playback session")
    if any(k in lower for k in ["加载会话", "恢复会话", "load session", "session load"]):
        name = _extract_after_prefix(text, ["加载会话", "恢复会话", "load session", "session load"])
        return ParsedIntent(["session", "load", name] if name else ["session", "load"], "load playback session")
    if any(k in lower for k in ["会话列表", "列出会话", "list sessions", "session list"]):
        return ParsedIntent(["session", "list"], "list sessions")
    if any(k in lower for k in ["删除会话", "删会话", "delete session", "session delete"]):
        name = _extract_after_prefix(text, ["删除会话", "删会话", "delete session", "session delete"])
        return ParsedIntent(["session", "delete", name] if name else ["session", "delete"], "delete session")

    if any(k in lower for k in ["导入备份", "恢复备份", "import backup", "restore backup"]):
        m = re.search(r"(\S+\.zip)\b", text)
        if m:
            return ParsedIntent(["import", "--in", m.group(1)], "import backup")
        return ParsedIntent(["commands"], "import backup (missing zip path)")
    if any(k in lower for k in ["导出数据", "导出备份", "备份", "export data", "export backup"]):
        return ParsedIntent(["export", "--out", "musichub-backup.zip"], "export backup")

    # Chinese/English current/status
    if any(k in lower for k in ["当前", "现在播放", "正在播放", "current", "what is playing", "status"]):
        if "守护" in text or "daemon" in lower:
            return ParsedIntent(["daemon", "status"], "daemon status request")
        return ParsedIntent(["current"], "current track request")

    # Stop / pause
    if any(k in lower for k in ["停止播放", "关掉音乐", "关闭音乐", "stop music", "stop playing", "quit music", "退出播放"]):
        return ParsedIntent(["stop"], "stop playback")
    if lower in {"stop", "停止", "关掉", "关闭"}:
        return ParsedIntent(["stop"], "stop playback")
    if any(k in lower for k in ["暂停", "继续播放", "pause", "resume", "恢复播放"]):
        return ParsedIntent(["pause"], "toggle pause")

    # Layer / overlay
    if any(k in lower for k in ["叠加播放", "同时播放"]):
        rest = text
        for prefix in ["叠加播放", "同时播放"]:
            idx = text.find(prefix)
            if idx != -1:
                rest = text[idx + len(prefix):].strip()
                break
        return ParsedIntent(["layer", rest] if rest else ["layer"], "layer overlay playback")
    if lower.startswith("layer "):
        return ParsedIntent(["layer", text[6:].strip()], "layer overlay playback")

    # Volume control: "vol 0 70" or "把X音量调到Y"
    vol_match = re.search(r"(?:^vol\s+|把.*?|音量.*?)(\d+|all)\s+(\d+)", lower)
    if vol_match:
        return ParsedIntent(["vol", vol_match.group(1), vol_match.group(2)], "volume control")
    vol_match_zh = re.search(r"第?\s*(\d+)\s*(?:个)?(?:槽位|slot)?.*?(?:音量).*?(?:到|为)\s*(\d+)", lower)
    if vol_match_zh:
        return ParsedIntent(["vol", vol_match_zh.group(1), vol_match_zh.group(2)], "volume control")

    if any(k in lower for k in ["loudnorm", "响度标准化", "响度均衡", "响度归一"]):
        if any(k in lower for k in ["关闭", "关掉", "off", "disable"]):
            return ParsedIntent(["af", "off"], "disable loudness normalization")
        if any(k in lower for k in ["开启", "打开", "on", "enable"]):
            return ParsedIntent(["af", "on"], "enable loudness normalization")
        return ParsedIntent(["af", "status"], "audio filter status")

    # Slots list
    if any(k in lower for k in ["查看槽位", "所有播放器", "所有slot", "list slots", "显示所有播放器"]):
        return ParsedIntent(["slots"], "list active slots")

    # Stop all
    if any(k in lower for k in ["全部停止", "停止所有", "stop all", "全停"]):
        return ParsedIntent(["stop", "all"], "stop all slots")

    # Like/dislike/next
    if any(k in lower for k in ["这首好", "好歌", "喜欢这首", "mark good", "like this", "thumbs up"]):
        return ParsedIntent(["good"], "positive feedback")
    if any(k in lower for k in ["不喜欢", "坏歌", "拉黑", "mark bad", "dislike", "thumbs down"]):
        return ParsedIntent(["bad"], "negative feedback")
    if any(k in lower for k in ["下一首", "切歌", "next song", "skip"]):
        return ParsedIntent(["next"], "skip/next")

    # Explicit "play ..." phrases should prefer search playback (YouTube via yt-dlp in cmd_play)
    # unless the user explicitly asks for recommendation queue playback.
    play_q = _extract_after_prefix(
        text,
        ["播放推荐", "播放 ", "听 ", "来一首 ", "来点 ", "放一下 ", "play ", "listen to "],
    )
    if play_q is not None:
        if not play_q:
            return ParsedIntent(["play"], "play default recommendations")
        if play_q.casefold() in {"推荐", "recommendations", "recommendation", "推荐歌", "推荐歌曲"}:
            return ParsedIntent(["play"], "play recommendations")
        return ParsedIntent(["play", play_q], "play/search request (youtube-first)")

    # Recommendations
    if any(k in lower for k in ["推荐", "recommend"]):
        avoid_match = re.search(r"(?:不要|别推|exclude)\s*([^\s,，。]+)", text, flags=re.IGNORECASE)
        if any(k in lower for k in ["播放", "来点", "play", "listen"]):
            if avoid_match:
                return ParsedIntent(["play", "--exclude-artist", avoid_match.group(1)], "play recommendations with artist exclusion")
            return ParsedIntent(["play"], "play recommendations")
        m = re.search(r"(?:top|前)\s*(\d+)", lower)
        if m:
            return ParsedIntent(["rec", "--limit", m.group(1)], "recommendations with limit")
        if avoid_match:
            return ParsedIntent(["rec", "--exclude-artist", avoid_match.group(1)], "recommendations with artist exclusion")
        return ParsedIntent(["rec"], "recommendations request")

    # Stats/profile
    if any(k in lower for k in ["统计", "画像", "偏好", "stats", "profile"]):
        return ParsedIntent(["stats"], "stats/profile request")

    # Init / doctor
    if any(k in lower for k in ["初始化", "init"]):
        return ParsedIntent(["init"], "initialize")
    if any(k in lower for k in ["检查环境", "doctor", "诊断"]):
        return ParsedIntent(["doctor"], "environment check")

    # Daemon controls
    if ("守护" in text or "后台同步" in text or "daemon" in lower or "background" in lower) and (
        "启动" in text or "开启" in text or "start" in lower
    ):
        return ParsedIntent(["daemon", "start"], "start daemon")
    if ("守护" in text or "后台同步" in text or "daemon" in lower or "background" in lower) and (
        "停止" in text or "关闭" in text or "stop" in lower
    ):
        return ParsedIntent(["daemon", "stop"], "stop daemon")
    if ("守护" in text or "后台同步" in text or "daemon" in lower or "background" in lower) and (
        "状态" in text or "status" in lower
    ):
        return ParsedIntent(["daemon", "status"], "daemon status")

    # Sync/import
    if any(k in lower for k in ["同步事件", "导入事件", "sync events"]):
        return ParsedIntent(["sync-events"], "sync mpv events")
    if any(k in lower for k in ["训练", "重训", "train", "retrain", "更新模型"]):
        if "implicit" in lower:
            return ParsedIntent(["train", "implicit"], "train implicit model")
        return ParsedIntent(["train", "all"], "train models")
    if any(k in lower for k in ["同步", "导入", "sync", "import"]):
        if "ytm" in lower or "youtube music" in lower or "youtube音乐" in text:
            return ParsedIntent(["sync", "ytm"], "sync ytm")
        if "网易" in text or "netease" in lower or "ncm" in lower:
            return ParsedIntent(["sync", "ncm"], "sync netease")

    # Note / Journal
    if lower.startswith("note ") or lower.startswith("笔记 ") or lower.startswith("记录 "):
        space_idx = text.find(" ")
        content = text[space_idx + 1 :].strip()
        return ParsedIntent(["note", content], "note taking request")
    if any(k in lower for k in ["查看日记", "我的日记", "journal", "查看笔记", "历史笔记"]):
        return ParsedIntent(["journal"], "journal review request")

    # URL fallback
    if lower.startswith("http://") or lower.startswith("https://"):
        return ParsedIntent(["play", text], "url playback")

    # Final fallback: treat as play/search query.
    return ParsedIntent(["play", text], "default search playback fallback")


def maybe_extract_direct_command(argv: list[str]) -> list[str] | None:
    if not argv:
        return None
    first = argv[0].casefold()
    return argv if first in KNOWN_COMMANDS else None
