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
    "slots",
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
        if any(k in lower for k in ["播放", "来点", "play", "listen"]):
            return ParsedIntent(["play"], "play recommendations")
        m = re.search(r"(?:top|前)\s*(\d+)", lower)
        if m:
            return ParsedIntent(["rec", "--limit", m.group(1)], "recommendations with limit")
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
