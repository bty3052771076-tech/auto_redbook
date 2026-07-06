# Auto Redbook

Auto Redbook 是一个面向小红书创作者中心的本地自动化工具。它可以生成图文草稿、保存到草稿箱、批量发布草稿、删除草稿、同步已发布数据，并用互动数据辅助选择下一批发文方向。

当前主线重点支持：

- `每日新闻`：从新闻源、单条新闻材料文件或多条新闻候选池生成小红书图文草稿。
- `每日AI讯息`：采集国内外 AI 模型、技术、产品动态，按官方模型源、AI HOT/搜索补充、Hugging Face 综合兜底分层筛选后生成多图简报。
- 已发布数据同步：严格全量同步小红书已发布笔记指标，未达到页面显示的 `全部 N` 时不会覆盖 latest 快照。
- 模型免费额度查询：通过 Aliyun 百炼与 Volcengine Ark 控制台页面读取可见额度/用量信息，并在 GUI 中可视化展示。

## 快速开始

以下命令默认你把项目放在非系统盘，例如 `E:\AI\codex\redbook_workflow`。不建议把依赖、浏览器缓存或运行数据安装到 C 盘。

### 1. 克隆项目

```powershell
Set-Location E:\AI\codex
git clone https://github.com/bty3052771076-tech/auto_redbook.git redbook_workflow
Set-Location E:\AI\codex\redbook_workflow
```

如果你已经有本地项目，直接进入项目目录即可。

### 2. 创建虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. 安装 Playwright 浏览器到工作区

首次使用小红书、Aliyun 或 Volcengine 控制台自动化时需要 Chromium。建议把浏览器缓存放在项目目录内：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 4. 配置 API Key

推荐使用环境变量或 GUI 配置页。不要把真实 API Key 写入 Git 仓库。

```powershell
# 供应商选择：auto / aliyun / volcengine / ppinfra
$env:LLM_PROVIDER="aliyun"
$env:IMAGE_PROVIDER="aliyun"

# Aliyun / DashScope
$env:DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
$env:ALIYUN_LLM_MODEL="glm-5.2"
$env:ALIYUN_IMAGE_MODEL="qwen-image-2.0-pro-2026-06-22"

# Volcengine Ark
$env:VOLCENGINE_API_KEY="YOUR_VOLCENGINE_API_KEY"
$env:VOLCENGINE_LLM_MODEL="glm-5.2"
$env:VOLCENGINE_IMAGE_MODEL="doubao-seedream-5-0-lite-260128"

# 可选新闻源 / 图片源
$env:NEWS_API_KEY="YOUR_NEWS_API_KEY"
$env:GNEWS_API_KEY="YOUR_GNEWS_API_KEY"
$env:JUHE_NEWS_APPKEY="YOUR_JUHE_NEWS_APPKEY"
$env:PEXELS_API_KEY="YOUR_PEXELS_API_KEY"
```

也可以复制 `docs/*api-key.example.md` 为去掉 `.example` 的本地文件后填写真实 key，例如：

```powershell
Copy-Item docs\volcengine_api-key.example.md docs\volcengine_api-key.md
```

不带 `.example` 的 key 文件已被 `.gitignore` 忽略，不应提交。

### 5. 登录浏览器 Profile

首次上传草稿或同步数据前，用可视浏览器登录小红书创作者中心：

```powershell
.\.venv\Scripts\python.exe -m apps.cli open-creator --login-hold 600
```

如果要查询 Aliyun / Volcengine 额度，也需要分别用对应控制台 profile 完成登录。GUI 和 CLI 会复用项目内的浏览器 profile。

### 6. 启动 GUI

```powershell
.\.venv\Scripts\python.exe -m apps.gui
```

也可以使用 Windows 启动脚本：

```powershell
.\Start-GUI.cmd
```

### 7. 生成一条每日新闻草稿

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --prompt "财经产业 / 公司政策 / 市场变化" `
  --evaluation-viewpoint "无视角评价" `
  --assets-glob "assets/empty/*" `
  --count 1 `
  --login-hold 600 `
  --wait-timeout 600 `
  --force
```

`--lookback-days N` 可固定新闻回溯窗口。留空时默认先找 3 天内新闻，不够再扩展到 7 天、14 天，仍不足则停止并说明素材不足。

### 8. 生成一条每日AI讯息草稿

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日AI讯息" `
  --assets-glob "assets/empty/*" `
  --count 1 `
  --login-hold 600 `
  --wait-timeout 600 `
  --force
```

`每日AI讯息` 会自动渲染本地简报图，不需要本地素材或 AI 生图。

## GUI 功能

- 自动发帖：生成 `每日新闻` 或 `每日AI讯息`，并保存到小红书草稿箱。
- 新闻材料：支持单条新闻材料文件和多条新闻候选池文件。单条材料固定生成 1 条，不使用提示词、数量和回溯筛选；多条材料会继续参与候选筛选。
- 多提示词：`每日新闻` 支持多个提示词输入框，每个框表示一个检索方向。
- 回溯天数：留空时按 3/7/14 天逐级扩展；填写数字时只使用发帖日 N 天内候选。
- 已发布数据：全量同步浏览、点赞、评论、收藏、分享等指标，严格校验 `全部 N`。
- 额度面板：在自动发帖页展示 Aliyun / Volcengine 模型额度，支持同步、搜索、排序和点击模型切换。
- 草稿管理：支持发布草稿、删除草稿，删除前建议先 dry-run。

## CLI 常用命令

查看本地帖子：

```powershell
.\.venv\Scripts\python.exe -m apps.cli list
.\.venv\Scripts\python.exe -m apps.cli show <post_id>
```

使用单条新闻材料生成一条草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --single-news-material-file "data/manual_news/one.md" `
  --assets-glob "assets/empty/*" `
  --login-hold 600 `
  --wait-timeout 600 `
  --force
```

使用多条新闻材料候选池生成多条草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --prompt "财经产业 / 公司政策 / 市场变化" `
  --news-materials-file "data/manual_news/today.md" `
  --assets-glob "assets/empty/*" `
  --count 3 `
  --login-hold 600 `
  --wait-timeout 600 `
  --force
```

发布草稿前预览：

```powershell
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --dry-run --date today --login-hold 600 --wait-timeout 600
```

发布草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --date today --limit 3 --yes --login-hold 600 --wait-timeout 600
```

删除草稿前预览：

```powershell
.\.venv\Scripts\python.exe -m apps.cli delete-drafts --draft-type image --limit 10 --dry-run --login-hold 600 --wait-timeout 600
```

全量同步已发布数据：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 0 --login-hold 600
```

分析已发布数据：

```powershell
.\.venv\Scripts\python.exe -m apps.cli analyze-metrics --save
```

查询 Aliyun 额度：

```powershell
.\.venv\Scripts\python.exe -m apps.cli aliyun-quota `
  --model glm-5.2 `
  --model qwen-image-2.0-pro-2026-06-22 `
  --login-hold 600 `
  --wait-timeout 120 `
  --save-raw
```

查询 Volcengine Ark 额度：

```powershell
.\.venv\Scripts\python.exe -m apps.cli volcengine-quota `
  --model glm-5.2 `
  --model deepseek-v4-pro `
  --model deepseek-v4-flash `
  --model doubao-seedream-5-0-lite-260128 `
  --login-hold 600 `
  --wait-timeout 120 `
  --save-raw
```

## 每日新闻规则

- 生成 `x` 条草稿时，会先获取更多原始候选，再按提示词相关性、时效性、热度和来源多样性筛选。
- 默认只使用发帖日、昨天、前天的新闻；素材不足时按 3/7/14 天规则扩展。
- 新闻 API 返回多条新闻时，会先聚焦最重要的一条故事，再生成标题、正文、评价和图片。
- 正文使用简体中文，不再写入“原文标题”段落。
- 单条新闻材料文件会优先使用 AI 生图；生图失败后再回退 Pexels。

## 每日AI讯息规则

- 默认最少 8 条，必须符合生成日回溯窗口内的新鲜度要求。
- 至少包含 3 条国内模型资讯和 3 条国外 AI 资讯；不足时停止并说明原因。
- 优先选择模型发布、模型版本、API、开发者工具、评测基准、开源项目和基础设施技术更新。
- 官方模型源优先，AI HOT/搜索补充其次，Hugging Face 这类综合模型发布站只作为最后兜底。
- 草稿正文会写入来源链接，图片中展示发布时间和来源，不写长链接。

当前内置模型源详见 `docs/每日AI讯息来源扩展与兜底分层-2026-07-06.md`。

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
docs/                 功能设计、修复记录、实测记录和 key 模板
```

## 本地数据与安全

以下内容默认只保留在本地，不应提交：

- `data/`：帖子、图片、运行记录、浏览器 profile、额度快照、已发布指标。
- `.env`、`.env.*`、`.env.gui`：本地环境变量。
- `docs/*api-key.md`：真实 API Key 文件。
- `.venv/`、`.playwright-browsers/`：本地运行环境。
- `output/`、`logs/`：调试输出。
- `AGENT.md`、`CODING_PROGRESS.md`：本地协作记录。

提交前建议运行：

```powershell
git status --short
git ls-files | Select-String -Pattern "api-key\.md$|(^|/)\.env($|\.)|data/|browser|\.key$|\.pem$|\.p12$|\.pfx$"
git grep -n -I -E "sk-[A-Za-z0-9]{20,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" -- .
```

如果上述命令发现真实密钥或本地数据，先移出 Git 跟踪再提交。

## 文档入口

- `docs/README.md`：按功能分类的文档索引。
- `docs/使用说明-自动新闻生成与草稿发布.md`：CLI / GUI 使用说明。
- `docs/模型与GUI供应商配置.md`：模型供应商、图片供应商和 GUI 配置说明。
- `docs/每日AI讯息来源扩展与兜底分层-2026-07-06.md`：每日 AI 讯息来源分层。
- `docs/模型免费额度查询-2026-07-03.md`：额度查询设计和使用方式。

## 测试

运行全部测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

常用专项测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_ai_digest_sources.py tests\test_ai_digest_collect.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_gui.py tests\test_published_metrics.py tests\test_published_post_sync.py -q
```

## 发布前检查

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q apps src tests
git diff --check
```

确认测试通过、无真实 API Key、无本地数据后再提交和推送。
