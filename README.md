# Auto Redbook Workflow

本项目用于在本地生成小红书图文内容，并通过 Playwright 自动保存到小红书创作者中心草稿箱。它支持普通图文、每日新闻、每日 AI 讯息、幽默虚构新闻、AI 配图、草稿发布、草稿删除、已发布数据同步与发布方向分析。

默认原则很简单：密钥和草稿数据只留在本机；上传和发布必须由你显式触发；不绕过小红书扫码、验证码或平台风控。

## 功能概览

- `普通图文`：标题 + 提示词 + 本地图片或 AI 配图，生成可上传草稿。
- `每日新闻`：从 NewsAPI、GNews、聚合数据 Juhe、hot_news 或本地候选文件获取新闻，清洗正文，生成中文新闻草稿。
- `每日AI讯息`：从官方 AI 博客、RSS、GitHub Release、国内模型厂商发布页获取约 10 条动态，渲染为多张简报图并保存草稿。
- `每日假新闻`：生成明显虚构、用于娱乐的新闻草稿，正文会包含虚构声明。
- `AI 配图`：默认使用阿里云百炼文生图；也可切换 Pexels 或本地 assets。
- `GUI`：图形界面可选择 LLM 供应商、图片来源、模型、上传参数、发布/删除草稿、同步已发布数据。
- `已发布数据分析`：同步点赞、评论、收藏、浏览数据到本地表格，并给出后续发布方向建议。
- `阿里云额度查询`：通过官方百炼控制台页面查看 LLM / 生图模型免费额度和到期信息。

## 环境准备

请不要在 C 盘安装项目依赖。推荐把虚拟环境、pip 缓存、Playwright 浏览器都放在当前工作区。

需要准备：

- Python 3.10+
- 小红书账号
- Chrome / Chromium 登录态
- 阿里云百炼 / DashScope 账号，用于 LLM 和生图
- 可选新闻源 Key：GNews、NewsAPI、聚合数据 Juhe
- 可选 Pexels Key：仅当你要用 Pexels 图片检索时需要

首次初始化：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

$env:PIP_CACHE_DIR=(Resolve-Path ".").Path + "\.pip-cache"
$env:PLAYWRIGHT_BROWSERS_PATH=(Resolve-Path ".").Path + "\.playwright-browsers"

pip install -r requirements.txt
python -m playwright install chromium
```

## 密钥配置

推荐使用 PowerShell 环境变量或 GUI 保存到本地 `.env.gui`。不要把真实 Key 写进 README、代码或提交到 GitHub。

```powershell
$env:LLM_PROVIDER="aliyun"
$env:ALIYUN_LLM_API_KEY="YOUR_DASHSCOPE_KEY"
$env:ALIYUN_LLM_MODEL="qwen3.7-plus"

$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_API_KEY="YOUR_DASHSCOPE_KEY"
$env:ALIYUN_IMAGE_MODEL="wan2.7-image"

$env:NEWS_PROVIDER="gnews"
$env:GNEWS_API_KEY="YOUR_GNEWS_API_KEY"
```

`.gitignore` 已忽略：

- `.env*`
- `docs/*api-key.md`
- `data/`
- `logs/`
- `output/`
- `.venv/`
- `.pip-cache/`
- `.playwright-browsers/`
- 本地 GUI exe

## 快速启动

启动 GUI：

```powershell
.\AutoRedbookGUI-Launcher.exe
```

或直接运行 Python GUI：

```powershell
.\.venv\Scripts\python.exe -m apps.gui
```

打开正确的小红书创作者中心 Profile：

```powershell
.\Open-XHS-Creator.cmd
```

GUI 使用的是工作区内的浏览器 profile，避免误用系统默认 Chrome 账号。

## 常用命令

生成并保存 1 条每日新闻草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --evaluation-viewpoint "无视角评价" --assets-glob "assets/empty/*" --count 1 --login-hold 600 --wait-timeout 600 --force
```

生成 1 条每日 AI 讯息简报草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --assets-glob "assets/empty/*" --count 1 --login-hold 600 --wait-timeout 600 --force
```

如果已经登录工作区 Chrome profile，可以无界面上传：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*" --count 1 --login-hold 0 --wait-timeout 600 --force --headless
```

只生成本地草稿，不上传：

```powershell
.\.venv\Scripts\python.exe -m apps.cli create --title "每日新闻" --assets-glob "assets/empty/*" --count 1
```

发布已上传到草稿箱的草稿，建议先 dry-run 预览：

```powershell
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --dry-run --date today --login-hold 600 --wait-timeout 600
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --date today --limit 3 --yes --login-hold 600 --wait-timeout 600
```

删除草稿，建议先 dry-run 预览：

```powershell
.\.venv\Scripts\python.exe -m apps.cli delete-drafts --draft-type image --limit 10 --dry-run --login-hold 600 --wait-timeout 600
.\.venv\Scripts\python.exe -m apps.cli delete-drafts --draft-type image --limit 10 --yes --login-hold 600 --wait-timeout 600
```

同步已发布数据：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 50 --login-hold 600 --wait-timeout 600
```

分析发布方向：

```powershell
.\.venv\Scripts\python.exe -m apps.cli analyze-metrics
.\.venv\Scripts\python.exe -m apps.cli analyze-metrics --save
```

查询阿里云百炼额度：

```powershell
.\.venv\Scripts\python.exe -m apps.cli aliyun-quota --model qwen3.7-plus --model wan2.7-image --login-hold 600 --wait-timeout 120
```

## 特殊标题工作流

### 每日新闻

当 `--title "每日新闻"` 时，程序会抓取新闻候选，获取原文上下文，调用 LLM 生成中文草稿，并保存新闻来源 metadata。

默认新闻源：

- NewsAPI
- GNews
- 聚合数据 Juhe 新闻头条
- 聚合数据 Juhe 财经新闻
- hot_news 热榜兜底
- 本地候选文件 `NEWS_CANDIDATES_FILE`

正文会按以下结构输出：

```text
原文标题：...

内容：
...

评价：
...

日期：YYYY-MM-DD

来源：来源名称
```

原始 URL 不写进正文，只保存到本地 `post.json`。

### 每日AI讯息

当 `--title "每日AI讯息"` 时，程序固定生成 1 条 AI 动态简报草稿；简报中默认约 10 条动态，数量由环境变量控制，而不是由 `--count` 重复生成多条。

主要配置：

```powershell
$env:AI_DIGEST_TARGET_ITEMS="10"
$env:AI_DIGEST_MIN_OFFICIAL_ITEMS="6"
```

默认主信源：

- OpenAI News
- Anthropic News
- Google DeepMind Blog
- Meta AI Blog
- Microsoft AI Blog
- NVIDIA Deep Learning Blog
- Hugging Face Blog
- Hugging Face Transformers GitHub Releases
- 阿里云百炼 / 通义
- 智谱 GLM
- MiniMax
- 火山方舟 / 豆包
- 百度千帆 / 文心
- 月之暗面 Kimi

可选补充/验证信源：

- X 搜索页
- Hacker News / Algolia 搜索页

官方信源足够时，社交/搜索源只用于验证；官方信源不足时，才作为补位候选。

### 每日假新闻

当 `--title "每日假新闻"` 时，程序会生成明显虚构的娱乐新闻草稿。建议提供 `--prompt` 指定主题。

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日假新闻" --prompt "火星快递导致地球外卖迟到" --assets-glob "assets/empty/*" --login-hold 600
```

## 图片来源

默认图片来源为阿里云百炼文生图：

```powershell
$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_MODEL="wan2.7-image"
$env:ALIYUN_IMAGE_SIZE="1104*1472"
```

常用模型：

- `wan2.7-image`
- `wan2.7-image-pro`
- `qwen-image-2.0-pro-2026-04-22`

如果本地 assets 命中图片，会优先使用本地图片；当使用 `assets/empty/*` 且无本地图片时，会触发自动配图。

## 输出位置

本地输出不会上传 GitHub：

- `data/posts/<post_id>/post.json`
- `data/posts/<post_id>/assets/`
- `data/runs/run_records.csv`
- `data/analytics/published_metrics.csv`
- `data/analytics/published_metrics_latest.csv`

每条新闻或 AI 简报都会保存来源 metadata，便于后续追溯。

## GUI 功能

GUI 入口：

```powershell
.\.venv\Scripts\python.exe -m apps.gui
```

GUI 支持：

- 一键生成并保存草稿
- 快捷标题：每日新闻、每日AI讯息、每日假新闻
- 选择 LLM 供应商和模型
- 选择图片来源和阿里云生图模型
- dry-run、无界面上传、login-hold、wait-timeout
- 删除草稿、发布草稿
- 同步已发布数据
- 表格查看点赞、评论、收藏、浏览，并按列排序
- 分析后续发布方向
- 查询阿里云百炼额度

## 测试

运行全量测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

运行 AI 简报相关测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ai_digest.py tests\test_ai_digest_sources.py tests\test_ai_digest_collect.py tests\test_ai_digest_generate.py tests\test_ai_digest_render.py tests\test_ai_digest_workflow.py -q
```

编译检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q apps src
```

## 安全提醒

- 不要提交真实 API Key。
- 不要提交 `data/` 下的草稿、浏览器 profile、运行记录或已发布数据。
- 不要提交 `.env.gui`。
- 上传 GitHub 前建议运行密钥扫描。
- 发布草稿前建议先 `publish-drafts --dry-run`。
- 删除草稿前建议先 `delete-drafts --dry-run`。

## 相关文档

- `docs/每日AI讯息功能说明-2026-06-30.md`
- `docs/assets/daily_ai_digest_concept_2026-06-30.png`
- `docs/阿里云百炼额度查询-2026-06-30.md`
- `docs/hot_news新闻源接入-2026-06-29.md`
- `docs/小红书草稿发布功能-2026-06-29.md`
- `docs/GUI共享草稿预览与发布同步-2026-06-29.md`
- `docs/聚合数据新闻源接入-2026-06-21.md`
- `docs/每日新闻正文渲染修复-2026-06-21.md`
- `docs/每日新闻历史URL查重-2026-06-20.md`
- `docs/模型与GUI供应商配置.md`
