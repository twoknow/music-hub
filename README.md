# music-hub

## 中文版

一个面向 Windows 的极简本地音乐工具。

它不是一个大而全的播放器，也不是一个复杂的媒体库管理器。
它更像一个安静的小工具：

- 你一句话说出想听什么，它就开始播
- 你听到喜欢的歌，按一下 `good`
- 你不喜欢，按一下 `bad` 或 `next`
- 你有一点心情，随手记一句 `note`
- 它把这些都留在本地，慢慢长成你自己的音乐偏好系统

音乐直指人心。
这个项目想做的，不是更复杂，而是更靠近人。
它是一个给自己用的、足够轻、足够近、足够治愈的听歌入口。

### 这是什么

`music-hub` 是一个基于 `mpv + yt-dlp + SQLite` 的本地优先音乐 CLI。

它当前的定位很明确：

- **Windows 优先**：这是一个 Windows 项目，安装和使用体验都优先为 Windows 打磨
- **技术小白友好**：尽量做到一键安装，开箱可用
- **自然语言优先**：你不必记住很多命令，可以直接说“播放周杰伦”“下一首”“这首好听”
- **本地优先**：播放记录、反馈、推荐数据默认留在本机
- **欢迎改造**：如果你想把它改成 macOS 版，欢迎直接 fork

### 它适合谁

- 想在 Windows 上拥有一个极简、安静、不打扰的听歌入口的人
- 不想折腾复杂播放器的人
- 想把“听歌”和“心情记录”放在一起的人
- 不想把自己的偏好完全交给云平台的人
- 想拿一个小而完整的项目继续改造成 macOS / Linux / GUI 版本的人

### 它现在能做什么

- 用自然语言搜索并播放 YouTube / YouTube Music 内容
- 记录 `good / bad / next / note` 等即时反馈
- 自动累计本地播放历史
- 基于历史生成简单推荐
- 开启 `radio` 做续播
- 用 `layer` 叠加第二层声音，比如白噪音、雨声、环境音
- 保存 / 恢复会话
- 导出 / 导入本地备份

### 快速开始

先准备好：

- Windows PowerShell
- Python 3.11+
- 7-Zip

然后执行：

```powershell
git clone https://github.com/twoknow/music-hub.git
cd music-hub
.\install.ps1
```

如果 PowerShell 阻止脚本执行，先运行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

安装完成后，先检查环境：

```powershell
m doctor
```

然后直接开始听：

```powershell
m "播放 周杰伦 稻香"
m "给我推荐"
m "这首好听"
m "下一首"
```

### 最推荐的使用方式

如果你是第一次用，最简单的开始方法是：

```powershell
m "播放 你现在最想听的歌"
m good
m note "这段旋律有点安定下来"
m "给我推荐"
```

你不需要一开始就理解所有命令。
把它当成一个会慢慢记住你口味的小工具就够了。

### 常见自然语言示例

```powershell
m "播放 周杰伦 稻香"
m "给我推荐"
m "下一首"
m "这首好歌"
m "不喜欢这首"
m "当前播放什么"
m "保存会话 工作流"
m "撤销上一步"
m "来点适合学习的"
```

你也可以使用显式命令：

```powershell
m play "许巍 蓝莲花"
m rec --limit 10 --why
m radio
m layer "white noise"
m vol 0 70
m stop all
```

完整命令可以看 `COMMANDS.md`。

### 为什么会有这个项目

这个项目不是先写一份宏大架构图，再照着造出来的。
它是从一个很实际的需求里慢慢长出来的：

1. 我想立刻播放一点音乐
2. 我想马上记下“喜欢”还是“不喜欢”
3. 我想让这些痕迹留在本地，而不是消失
4. 我想让它慢慢变成一个真正属于自己的音乐角落

所以它今天的形态，不是一个炫技项目，而是一个从真实使用场景里长出来的工具。

### 数据与隐私

`music-hub` 默认是本地优先的。

- 你的数据库、日志、模型缓存都在本地 `data/` 目录
- `data/` 已被 `.gitignore` 忽略，不会随着正常提交进入仓库
- 你可以自己导出备份，也可以迁移到另一台机器

如果你在公开仓库里继续开发，请保持这个约定，不要手动把 `data/` 强行提交上去。

### 如果你想继续改

这个项目很欢迎被改。

尤其欢迎这些方向：

- 改成 macOS 版
- 改成 Linux 版
- 做一个更友好的 GUI
- 接更多音乐源
- 把推荐算法做得更聪明

这个项目虽然现在是 Windows 优先，但核心链路并不复杂：

`自然语言 / CLI -> mpv -> 事件记录 -> SQLite -> 推荐`

所以如果你愿意动手，它很适合作为一个继续生长的起点。

---

## English

A local-first music CLI for Windows.

`music-hub` is not trying to be a full music platform or a heavy desktop player.
It is a small, quiet tool for a simple loop:

- say what you want to hear
- play it immediately
- mark what you like
- skip what you do not
- leave a small note if the music hits you
- keep that trail locally

Music reaches people directly.
This project exists to make that experience simpler, lighter, and closer.

### What it is

`music-hub` is a local-first music CLI built on top of `mpv`, `yt-dlp`, and `SQLite`.

Its current direction is intentionally clear:

- **Windows-first**: this project is designed and polished for Windows
- **Beginner-friendly**: the goal is one-click setup and immediate use
- **Natural-language-first**: you can say things like “play Jay Chou”, “next song”, or “I like this one”
- **Local-first**: listening history, feedback, and recommendation data stay on your machine
- **Hackable**: if you want to port it to macOS, fork it and build on it

### Who it is for

- Windows users who want a minimal personal music workflow
- beginners who want something easier than setting up a full media stack
- people who want listening and mood notes to live together
- users who prefer local history over platform-controlled memory
- developers who want a small codebase to adapt into macOS, Linux, or GUI variants

### What it can do

- play YouTube / YouTube Music content by search or URL
- accept natural-language commands in Chinese and English
- record lightweight feedback such as `good`, `bad`, `next`, and `note`
- build local listening history
- generate simple recommendations
- continue playback with `radio`
- layer ambient audio with `layer`
- save sessions and import/export backups

### Quick Start

Recommended prerequisites:

- Windows PowerShell
- Python 3.11+
- 7-Zip

Then run:

```powershell
git clone https://github.com/twoknow/music-hub.git
cd music-hub
.\install.ps1
```

If PowerShell blocks script execution:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

Verify the setup:

```powershell
m doctor
```

Then start playing:

```powershell
m "play meditation music"
m "播放 周杰伦 稻香"
```

### Recommended first workflow

If you are new to the project, start here:

```powershell
m "play something you want right now"
m good
m note "this melody feels calming"
m "recommend something for me"
```

You do not need to learn every command first.
Treat it as a small tool that gradually learns your taste.

### Example commands

```powershell
m play "Xu Wei Blue Lotus"
m rec --limit 10 --why
m radio
m layer "white noise"
m vol 0 70
m stop all
```

You can also rely on natural language:

```powershell
m "give me recommendations"
m "next song"
m "I like this one"
m "what is playing now"
```

See `COMMANDS.md` for a fuller command list.

### Why this project exists

This project was not designed as a large product from day one.
It grew from a very simple need:

1. play something immediately
2. keep a small trace of what feels right
3. let those traces stay local
4. slowly turn listening history into something personal

So this is not a “look how much tech I used” project.
It is a tool shaped by actual use.

### Privacy

`music-hub` is local-first by default.

- your database, logs, and caches live under the local `data/` directory
- `data/` is ignored by Git in normal workflows
- you can export backups and move them to another machine if needed

If you continue developing this project in public, keep that rule intact and do not force-add local data into the repository.

### For developers

This project is intentionally small.

If you want to:

- port it to macOS
- port it to Linux
- build a GUI on top
- add more sources
- make the recommendation layer smarter

this repository is meant to be a good starting point.

The core path is simple:

`CLI / natural language -> mpv -> event log -> SQLite -> recommendation`

That is why it is Windows-first today, but not conceptually locked to Windows forever.
