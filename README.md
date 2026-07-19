# Auto Redbook

Auto Redbook 是一个运行在本地的中文内容生产工具，面向小红书创作者中心。它负责采集和筛选新闻、生成图文内容、保存草稿、同步已发布数据，并用实际互动数据辅助下一轮选题。

当前版本的主要能力：

- `每日新闻`：从多来源候选池中按检索关键词、时效性、热度和来源多样性筛选新闻，生成标题、正文、评价和配图。
- `每日AI讯息`：采集国内外模型、版本、API、开发工具、开源项目和基础设施动态，生成带发布时间与来源链接的多页简报。
- 新闻材料模式：支持单条材料直生成和多条材料候选池筛选。
- 小红书草稿：通过本地 Playwright 浏览器 Profile 实际保存到创作者中心草稿箱。
- 已发布数据：全量同步已发布笔记的浏览、点赞、评论、收藏等指标，并生成选题分析。
- 模型额度：通过 Aliyun 百炼和 Volcengine Ark 官方控制台页面读取可见免费额度/用量，在 GUI 中搜索、排序和切换模型。
- 配图策略：普通新闻优先使用 AI 生图，生图失败时可回退 Pexels；`每日AI讯息` 使用本地简报渲染图。

## 快速开始

以下示例以 Windows PowerShell 为准。建议将项目、虚拟环境和 Playwright 浏览器缓存放在非系统盘，例如 `E:\AI\codex`；本项目不会要求在 C 盘安装依赖。

### 1. 获取项目

```powershell
Set-Location E:\AI\codex
git clone https://github.com/bty3052771076-tech/auto_redbook.git redbook_workflow
Set-Location E:\AI\codex\redbook_workflow
```

已有本地副本时，直接进入项目目录即可。

### 2. 创建运行环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

首次使用自动化浏览器时，将 Chromium 安装到工作区：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 3. 配置模型

真实密钥只放在本地环境变量或未跟踪的 key 文件中。下面的值是占位符，不能替换成真实密钥后提交到 GitHub。

Aliyun / DashScope 示例：

```powershell
$env:LLM_PROVIDER="aliyun"
$env:IMAGE_PROVIDER="aliyun"
$env:DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
$env:ALIYUN_LLM_MODEL="glm-5.2"
$env:ALIYUN_IMAGE_MODEL="qwen-image-2.0-pro-2026-06-22"
```

Volcengine Ark 示例：

```powershell
$env:LLM_PROVIDER="volcengine"
$env:IMAGE_PROVIDER="volcengine"
$env:VOLCENGINE_API_KEY="YOUR_VOLCENGINE_API_KEY"
$env:VOLCENGINE_LLM_MODEL="deepseek-v4-pro"
$env:VOLCENGINE_IMAGE_MODEL="doubao-seedream-5-0-lite-260128"
```

`deepseek-v4-pro` 是控制台中的用户侧名称。当前 Ark OpenAI 兼容接口需要使用带日期的部署 ID，程序会自动将它映射为 `deepseek-v4-pro-260425`。因此 GUI 和 CLI 可以继续使用控制台名称，不要手工把真实端点或密钥写进代码。

还支持 `ppinfra` 和 `auto` LLM 提供商；完整变量、回退顺序和图片尺寸配置见 [`docs/模型与GUI供应商配置.md`](docs/模型与GUI供应商配置.md)。

每日新闻的可选信源凭据使用 [`docs/news_sources_api-key.example.md`](docs/news_sources_api-key.example.md) 模板：复制为本地 `docs/news_sources_api-key.md` 后填入 NewsData.io、Alpha Vantage、TheNewsAPI、Finnhub 的 key。该本地文件已被 Git 忽略；配置后自动候选池会将可用信源与现有 NewsAPI、GNews、聚合数据及 RSS 一起纳入筛选。

### 4. 登录浏览器 Profile

首次上传草稿或同步小红书数据时，以可视模式登录创作者中心：

```powershell
.\.venv\Scripts\python.exe -m apps.cli open-creator --login-hold 600
```

无窗口模式要求 Profile 已经登录：

```powershell
.\.venv\Scripts\python.exe -m apps.cli open-creator --headless --login-hold 0
```

Aliyun 和 Volcengine 控制台的额度页面可能使用独立 Profile。额度首次同步失败时，先用可视模式登录对应官方控制台，再运行 `sync-quotas`。

### 5. 启动 GUI

```powershell
.\.venv\Scripts\python.exe -m apps.gui
```

或者运行：

```powershell
.\Start-GUI.cmd
```

GUI 的“自动发帖”页面按内容与来源、材料模式、本次模型、运行设置组织：可在实时检索、单条材料和多条材料之间切换，只显示当前真正生效的输入；右侧“任务监控”批量显示步骤日志和模型额度。“已发布数据”页面执行全量同步和分析。

## 常用命令

`关键词`只用于扩展检索查询和筛选候选新闻，不是写作指令。正文、标题和评价的专业新闻写法由程序内部规则统一控制；CLI 的主参数为 `--keywords`，旧的 `--prompt` 仍可用于兼容已有脚本。

### 生成每日新闻

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --keywords "财经产业 公司政策 市场变化 / 国际冲突 外交安全 / 硬科技 芯片 AI" `
  --evaluation-viewpoint "无视角评价" `
  --assets-glob "assets/empty/*" `
  --count 10 `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

生成 `x` 条草稿时，程序会先跨信源积累更大的原始候选池，再去重、按关键词匹配和新闻质量筛选。默认候选目标约为 `20x`，至少尽量达到 `10x`；来源耗尽或时间窗内素材不足时，会输出各阶段数量和停止原因。

### 生成每日AI讯息

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日AI讯息" `
  --count 1 `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

每日 AI 讯息默认要求至少 8 条合格动态，并优先满足国内模型和国外 AI 资讯配额。所有条目必须有可追溯来源和真实发布时间；不满足时间、来源或内容门禁时宁可少生成，也不会用旧消息补数。

### 回溯天数

`--lookback-days N` 可以固定只使用发帖日向前 `N` 天的候选。留空时按北京时间自动尝试 `3 -> 7 -> 14` 天窗口；14 天仍不足时停止并在终端和 GUI 状态区说明“素材不足”。

### 人工新闻材料

单条材料模式固定生成一条，绕过在线候选筛选：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --single-news-material-file "data/manual_news/one.md" `
  --assets-glob "assets/empty/*" `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

多条材料模式把文件作为候选池，仍会使用关键词、数量和回溯天数筛选：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --keywords "财经产业 公司政策 市场变化" `
  --news-materials-file "data/manual_news/today.md" `
  --assets-glob "assets/empty/*" `
  --count 3 `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

两个材料参数互斥。单条材料模式优先 AI 生图，失败后回退到 Pexels（已配置对应 Key 时）。

### 已发布数据与分析

全量同步不会以固定页面等待时间作为完成条件，而是等待列表抓取、详情指标采集和总数校验完成后再关闭页面：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics `
  --limit 0 `
  --headless `
  --login-hold 0

.\.venv\Scripts\python.exe -m apps.cli analyze-metrics --save
```

同步期间会持续输出当前阶段、已抓取数量、目标数量和耗时。若全量校验未通过，程序不会覆盖有效的 latest 快照。

### 免费额度

按需查询指定模型：

```powershell
.\.venv\Scripts\python.exe -m apps.cli aliyun-quota `
  --model glm-5.2 `
  --model qwen-image-2.0-pro-2026-06-22 `
  --login-hold 600 `
  --wait-timeout 120 `
  --save-raw

.\.venv\Scripts\python.exe -m apps.cli volcengine-quota `
  --model glm-5.2 `
  --model deepseek-v4-pro `
  --model deepseek-v4-flash `
  --model doubao-seedream-5-0-lite-260128 `
  --login-hold 600 `
  --wait-timeout 120 `
  --save-raw
```

同步两个平台并更新 GUI 使用的快照：

```powershell
.\.venv\Scripts\python.exe -m apps.cli sync-quotas `
  --headless `
  --login-hold 0 `
  --wait-timeout 120
```

如果控制台页面没有展示可解析的数字，结果会保留 `unknown` 或 `quota_not_returned`，并记录警告；这表示页面或平台接口没有返回数据，不代表程序把额度解释成了 0。需要刷新登录态时，去掉 `--headless` 并保持可视浏览器。

### 草稿管理

```powershell
# 查看本地帖子
.\.venv\Scripts\python.exe -m apps.cli list
.\.venv\Scripts\python.exe -m apps.cli show <post_id>

# 发布前预览，再实际发布
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --dry-run --date today --login-hold 600
.\.venv\Scripts\python.exe -m apps.cli publish-drafts --date today --limit 3 --yes --login-hold 600

# 删除前先 dry-run
.\.venv\Scripts\python.exe -m apps.cli delete-drafts --draft-type image --limit 10 --dry-run --login-hold 600
```

## 内容与信源规则

### 每日新闻

- 在线采集会跨来源累积原始候选，优先已配置 API 和可靠媒体，再使用公开 RSS、搜索补充和最后的热度兜底。NewsData.io 适合综合覆盖；Alpha Vantage、Finnhub 优先补财经产业和公司市场；TheNewsAPI 补少量国际要闻。
- 当前中文补充包含新华社、人民网、央视网、中国政府网和中国新闻网的公开内容；台湾及海外中文媒体不计入中国大陆新闻配额。
- 多条新闻 API 返回时，先聚焦一条最重要的故事，再生成标题、正文、评价和图片，避免一条草稿混入多个不相关事件。
- 默认只使用发帖日、昨天和前天的新闻；候选不足时按 3/7/14 天扩展，旧于最终窗口的条目直接舍弃。
- 生成超过 2 条时至少包含 1 条中国大陆新闻；超过 5 条时至少包含 2 条中国大陆新闻。
- 正文使用简体中文，不写“原文标题”段落；每日新闻的来源链接保存在本地元数据，避免将长链接写入草稿正文。
- 写作时严格区分已核事实、来源表述、计划安排和分析判断，并区分发生时间、发布时间与当前状态；通用规则见 [`docs/权威发布写法与GUI性能信息架构优化-2026-07-19.md`](docs/权威发布写法与GUI性能信息架构优化-2026-07-19.md)。

### 每日AI讯息

- 官方模型动态优先，AI 搜索/热点补充其次，Hugging Face 等综合模型站作为最后兜底。
- 优先模型发布、版本更新、API、开发者工具、评测、开源项目和基础设施；观点讨论类内容只作补充。
- 每一页展示发布时间，正文保存来源链接；图片不放长链接。
- 真实日期由来源发布时间和北京时间窗口决定，模型不得自行改写成“今天”或其他日期。

## 目录结构

```text
apps/                 CLI、GUI 和端到端入口
src/news/             每日新闻候选获取、去重和筛选
src/ai_digest/        每日AI讯息采集、排序、生成和渲染
src/llm/              LLM 调用封装
src/images/           Aliyun、Volcengine、Pexels 和本地图片处理
src/publish/           小红书创作者中心 Playwright 自动化
src/analytics/        已发布数据同步和分析
src/storage/          本地 JSON/CSV/JSONL 存储
tests/                单元测试和回归测试
docs/                 设计、修复、实测和配置文档
```

## 本地数据与密钥安全

下列内容只应保留在本地，默认不会提交：

- `data/`、`logs/`、`output/`：帖子、图片、运行记录、额度快照和同步数据。
- `.env`、`.env.*`、`.env.gui`：本地环境变量。
- `docs/*api-key.md`：真实密钥文件；只提交对应的 `.example.md` 模板。
- `.venv/`、`.playwright-browsers/`：本地运行环境和浏览器缓存。
- 浏览器 Profile、登录态、Cookie、证书和私钥文件。
- `AGENT.md`、`CODING_PROGRESS.md`：本地协作记录。

提交前检查：

```powershell
git status --short
git diff --check
git ls-files | Select-String -Pattern "api-key\.md$|(^|/)\.env($|\.)|^data/|browser|\.key$|\.pem$|\.p12$|\.pfx$"
git grep -n -I -E "sk-[A-Za-z0-9]{20,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" -- .
```

发现真实密钥或登录数据时，先移出 Git 跟踪范围；不要通过提交后再删除的方式处理泄漏。

## 文档入口

- [`docs/README.md`](docs/README.md)：按功能分类的文档索引。
- [`docs/使用说明-自动新闻生成与草稿发布.md`](docs/使用说明-自动新闻生成与草稿发布.md)：CLI、GUI、生成和草稿发布。
- [`docs/模型与GUI供应商配置.md`](docs/模型与GUI供应商配置.md)：模型供应商、图片供应商和 GUI 配置。
- [`docs/每日AI讯息来源扩展与兜底分层-2026-07-06.md`](docs/每日AI讯息来源扩展与兜底分层-2026-07-06.md)：每日 AI 讯息来源分层。
- [`docs/模型免费额度查询-2026-07-03.md`](docs/模型免费额度查询-2026-07-03.md)：额度查询设计和使用方式。
- [`docs/每日新闻多API信源扩充与质量实测-2026-07-18.md`](docs/每日新闻多API信源扩充与质量实测-2026-07-18.md)：新增多 API 信源、质量实测与适用领域。
- [`docs/每日新闻火山DeepSeek端点与10条草稿实测-2026-07-16.md`](docs/每日新闻火山DeepSeek端点与10条草稿实测-2026-07-16.md)：最新一轮全量同步、模型端点和草稿箱实测。
- [`docs/权威发布写法与GUI性能信息架构优化-2026-07-19.md`](docs/权威发布写法与GUI性能信息架构优化-2026-07-19.md)：权威发布通用写法、生成草稿页面、任务监控和性能优化。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q apps src tests
git diff --check
```

网络供应商、控制台登录态和小红书账号属于外部条件，端到端实测记录保存在 `docs/`；真实密钥、本地数据和浏览器登录态不会提交到仓库。
