# Auto Redbook

Auto Redbook 是一个面向小红书创作者中心的本地自动化工具，用于生成图文草稿、保存到草稿箱、发布草稿、同步已发布数据，并基于互动数据辅助选择下一批新闻方向。

当前版本重点支持两类内容：

- `每日新闻`：从新闻源获取候选，筛选单条重点新闻，生成标题、正文、评价和配图。
- `每日AI讯息`：收集近 3 个北京时间自然日内的 AI 技术、模型、产品动态，去重后生成一条多图简报。

当前主线版本还包含严格的已发布数据同步保护：同步必须达到小红书页面显示的 `全部 N`，否则不会覆盖最新分析表。

## 功能概览

- CLI 与 Tkinter GUI 两套入口。
- 支持 Aliyun 百炼 / DashScope 与 Volcengine Ark 作为 LLM 供应商。
- 支持 Aliyun 图像模型、Volcengine Seedream、Pexels 或本地素材作为图片来源。
- 自动打开小红书创作者中心并保存图文草稿。
- 支持从草稿箱批量发布、删除草稿。
- 支持全量同步已发布笔记的浏览、点赞、评论、收藏、分享等指标。
- `published_metrics_latest.csv` 只保存本次同步快照，不混入历史脏数据；历史快照继续保存在 JSONL/CSV 中。
- 支持查询 Aliyun 百炼与 Volcengine Ark 控制台中的模型免费额度或使用情况。
- 本地保存运行记录、帖子 JSON、图片素材和同步结果，方便复盘。

## 环境要求

- Windows + PowerShell。
- Python 3.10 或更高版本。
- 已登录的小红书创作者中心账号。
- 可用的模型 API Key。至少配置一个 LLM 供应商；如果使用自动配图，需要配置图片供应商或提供本地素材。

首次安装依赖：

```powershell
Set-Location E:\AI\codex\redbook_workflow
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Playwright 首次使用需要 Chromium。建议把浏览器缓存放在工作区内，避免写入系统盘：

```powershell
Set-Location E:\AI\codex\redbook_workflow
$env:PLAYWRIGHT_BROWSERS_PATH="$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 配置

推荐使用环境变量或 GUI 的配置页。不要把真实 API Key 提交到仓库。

常用变量：

```powershell
# LLM 供应商：auto / aliyun / volcengine / ppinfra
$env:LLM_PROVIDER="aliyun"
$env:IMAGE_PROVIDER="aliyun"

# Aliyun / DashScope
$env:DASHSCOPE_API_KEY="..."
$env:ALIYUN_LLM_MODEL="glm-5.2"
$env:ALIYUN_IMAGE_MODEL="qwen-image-2.0-pro-2026-04-22"

# Volcengine Ark
$env:VOLCENGINE_API_KEY="..."
$env:VOLCENGINE_LLM_MODEL="doubao-seed-2-1-turbo-260628"
$env:VOLCENGINE_IMAGE_MODEL="doubao-seedream-5-0-lite-260128"

# 可选新闻与图片源
$env:NEWS_API_KEY="..."
$env:GNEWS_API_KEY="..."
$env:JUHE_API_KEY="..."
$env:PEXELS_API_KEY="..."
```

也可以先创建本地私有目录，再放入 key 文件，例如 `docs/aliyun_image_api-key.md`、`docs/volcengine_api-key.md`、`docs/news_api-key.md`：

```powershell
New-Item -ItemType Directory -Force docs
```

`docs/` 已作为本地私有目录忽略，不会上传到 GitHub。

## GUI 使用

启动 GUI：

```powershell
Set-Location E:\AI\codex\redbook_workflow
.\.venv\Scripts\python.exe -m apps.gui
```

如果已构建本地启动器，也可以运行：

```powershell
.\Start-GUI.cmd
```

GUI 中常用页签：

- 生成并上传：选择内容类型、模型供应商、图片来源，生成并保存到小红书草稿箱；当前公开入口不再提供“仅生成”。
- 已发布数据：全量同步已发布笔记指标，并分析下一批选题方向；默认要求严格全量，缺失时不覆盖 latest。
- 发布草稿：从小红书草稿箱中发布本地已记录的草稿。
- 删除草稿：按条件删除草稿箱内容，建议先 dry-run。
- 配置：填写本地环境变量和查询模型免费额度。

## CLI 常用命令

生成一条 `每日新闻` 并保存到草稿箱：

```powershell
Set-Location E:\AI\codex\redbook_workflow
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --prompt "财经产业 / 公司政策 / 市场变化" --evaluation-viewpoint "无视角评价" --assets-glob "assets/empty/*" --count 1 --login-hold 600 --wait-timeout 600 --force
```

生成一条 `每日AI讯息` 并保存到草稿箱：

```powershell
Set-Location E:\AI\codex\redbook_workflow
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --assets-glob "assets/empty/*" --count 1 --login-hold 600 --wait-timeout 600 --force
```

已登录 profile 后可尝试无界面运行：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*" --count 1 --login-hold 0 --wait-timeout 600 --force --headless
```

查看本地帖子：

```powershell
.\.venv\Scripts\python.exe -m apps.cli list
.\.venv\Scripts\python.exe -m apps.cli show <post_id>
```

重新保存某条草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli retry <post_id> --force --login-hold 600 --wait-timeout 600
```

发布草稿前建议先预览：

```powershell
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --dry-run --date today --login-hold 600 --wait-timeout 600
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --date today --limit 3 --yes --login-hold 600 --wait-timeout 600
```

删除草稿前建议先预览：

```powershell
.\.venv\Scripts\python.exe -m apps.cli delete-drafts --draft-type image --limit 10 --dry-run --login-hold 600 --wait-timeout 600
.\.venv\Scripts\python.exe -m apps.cli delete-drafts --draft-type image --limit 10 --yes --login-hold 600 --wait-timeout 600
```

## 已发布数据同步

全量同步已发布笔记指标：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 0 --login-hold 600
```

已登录 profile 的无界面同步：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 0 --headless --login-hold 0
```

默认是严格全量：

- `--limit 0`：按页面显示的 `全部 N` 全量采集。
- `--limit N`：采集请求范围内的 N 条。
- 如果页面显示 `全部 322` 但只采到 `317`，不会覆盖 latest 文件。
- 如果页面初始还没显示 `全部 N`，采集过程中会继续刷新目标数；目标数未知时不会把“已采到数量”误判为完整。
- 同标题但不同发布时间/统计数字的无链接卡片会被保留，避免被过度合并。
- 标题中包含 `点赞`、`浏览` 等普通语义词不会被误过滤，`未通过`、`查看修改建议` 等状态/操作行不会被当作标题。
- 只有显式传入 `--allow-partial` 才允许保存部分结果。

全量同步不会把“页面等待时间”当作任务总截止时间。页面会在采够目标数量，或明确判定本轮未完成并返回错误后关闭。

如果已发布内容较多或平台懒加载较慢，可临时提高滚动容忍度：

```powershell
$env:XHS_METRICS_MAX_SCROLLS="520"
$env:XHS_METRICS_STAGNANT_ROUNDS="220"
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 0 --login-hold 0 --wait-timeout 90
```

最近一次严格全量实测结果：`fetched=335 target=335 required=335 missing=0 complete=True`，`published_metrics_latest.csv` 写入 335 条本次快照。

分析已发布数据：

```powershell
.\.venv\Scripts\python.exe -m apps.cli analyze-metrics
.\.venv\Scripts\python.exe -m apps.cli analyze-metrics --save
```

## 模型额度查询

Aliyun 百炼：

```powershell
.\.venv\Scripts\python.exe -m apps.cli aliyun-quota --model glm-5.2 --model qwen-image-2.0-pro-2026-04-22 --login-hold 600 --wait-timeout 120
```

Volcengine Ark：

```powershell
.\.venv\Scripts\python.exe -m apps.cli volcengine-quota --model doubao-seed-2-1-turbo-260628 --model doubao-seedream-5-0-lite-260128 --login-hold 600 --wait-timeout 120
```

这两个命令通过官方控制台页面读取信息，不调用付费推理接口。

## 本地数据

仓库只保存代码、测试、启动脚本和 README。以下内容默认只保留在本地：

- `data/`：帖子、图片、运行记录、已发布指标。
- `output/`：调试输出。
- `docs/`：本地任务记录、API Key 文件、临时说明。
- `AGENT.md`、`CODING_PROGRESS.md`：本地协作记录。
- `.venv/`、`.playwright-browsers/`：本地运行环境。

## 项目结构

```text
apps/                 CLI、GUI 和端到端入口
scripts/              Windows 启动器和辅助脚本
src/ai_digest/        每日AI讯息采集、排序、生成和渲染
src/news/             每日新闻候选获取与筛选
src/llm/              LLM 调用封装
src/images/           Aliyun、Volcengine、Pexels 和本地图片处理
src/publish/          小红书创作者中心 Playwright 自动化
src/analytics/        已发布数据同步和分析
src/storage/          本地 JSON/CSV/JSONL 存储
tests/                单元测试和回归测试
```

## 测试

运行核心测试：

```powershell
Set-Location E:\AI\codex\redbook_workflow
.\.venv\Scripts\python.exe -m pytest -q
```

只验证 GUI 参数和已发布数据同步逻辑：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_published_post_sync.py tests\test_published_metrics.py tests\test_gui.py -q
```

## 安全说明

- 不要提交真实 API Key、浏览器 profile、草稿数据、运行截图或已发布指标。
- 首次连接小红书、Aliyun、Volcengine 控制台时建议使用可视浏览器完成登录。
- 自动发布和删除草稿前先使用 dry-run。
- 生成式模型输出需要人工复核，尤其是新闻事实、时间、来源和图片适配性。
