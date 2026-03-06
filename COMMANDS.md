# Music Hub CLI 命令手册

Music Hub 是一个基于 mpv + yt-dlp + SQLite 的极简音乐偏好系统。支持自然语言解析和多源搜索。

## 常用播放控制

| 命令 | 描述 | 示例 |
| :--- | :--- | :--- |
| `m play [query]` | 搜索并播放（支持 URL 或关键词） | `m play "许巍 蓝莲花"` |
| `m layer [query]` | 叠加播放一层新的音频（不影响当前播放） | `m layer "雨声"` |
| `m next` | 跳过当前曲目 | `m next` |
| `m pause` | 暂停/恢复 | `m pause` |
| `m stop [slot]` | 停止播放（默认 slot 0, 支持 all） | `m stop all` |
| `m vol [level]` | 设置音量 (0-130) | `m vol 80` |

## 评价与偏好 (影响推荐)

| 命令 | 描述 | 示例 |
| :--- | :--- | :--- |
| `m good` | 标记当前曲目为“喜欢”（自动记录高光时间点） | `m good` |
| `m bad` | 标记当前曲目为“讨厌” | `m bad` |
| `m note [文字]` | 记录此刻听歌的心境或灵感（自动关联时间点/章节） | `m note "这里的感觉像是在大雨中奔跑"` |
| `m undo` | 撤销上一次的评价或跳过操作 | `m undo` |

## 智能推荐与回顾

| 命令 | 描述 | 参数 |
| :--- | :--- | :--- |
| `m journal` | 查看你记录的“音乐心境日记” | `--limit 20` |
| `m rec` | 显示当前的推荐列表 | `--limit 10`, `--why` (显示理由) |
| `m play` | (不带参数) 自动开始播放推荐队列 | `--queue 5` (预加载数量) |

## 数据同步与管理

| 命令 | 描述 | 示例 |
| :--- | :--- | :--- |
| `m sync ytm` | 同步 YouTube Music 历史/收藏 | `m sync ytm --auth-json auth.json` |
| `m sync ncm` | 同步网易云音乐数据 | `m sync ncm --json export.json` |
| `m stats` | 查看个人音乐画像统计 | `m stats` |
| `m export` | 导出完整数据库备份 | `m export --out backup.zip` |
| `m import` | 从备份恢复数据 | `m import --in backup.zip` |

## 系统维护

| 命令 | 描述 | 示例 |
| :--- | :--- | :--- |
| `m doctor` | 检查环境依赖和守护进程 | `m doctor` |
| `m daemon start` | 启动后台事件同步守护进程 | `m daemon start` |
| `m slots` | 查看当前活跃的播放槽位 | `m slots` |
| `m ask` | 自然语言解析器 | `m ask "播放最近喜欢的歌"` |

---
*注：本手册由 Gemini CLI 自动生成。*
