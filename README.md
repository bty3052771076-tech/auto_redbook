# Auto Redbook

> 当前公开版本：2026-09-13。项目面向 Windows 本地运行，建议将项目、虚拟环境和浏览器缓存放在非系统盘。

Auto Redbook 是一个运行在 Windows 本地的中文内容生产与草稿分发工具。它从多种新闻和 AI 官方信源采集材料，生成图文内容，保存到小红书创作者中心和今日头条草稿箱，并同步小红书已发布内容的互动数据。

> 当前版本以本地运行和人工复核为前提。它不会替你绕过平台登录、短信验证、风控或发布审核，也不会把 API Key 自动上传到 GitHub。

## 当前能力

- 每日新闻：从多信源候选池采集约 20x 原始材料，按时效、热度、关键词、来源多样性和质量筛选，再生成标题、正文、评价和配图。
- 每日AI讯息：优先读取模型厂商官网、官方公告、官方 GitHub 和官方社交账号；只保留北京时间生成日及前一日的可追溯信息，按事件级查重和信源上限筛选，最终动态数量按高质量候选自动决定，范围为 1–20 条，不再硬凑 8 条。
- 材料发帖：支持单条/多条文件，也支持 GUI 直接粘贴文字；材料模式需要材料时间，但不套用在线新闻的日期窗口。
- 多平台草稿：支持小红书、今日头条或两个平台；保存后会回到创作者中心进行标题、正文和图片读回验证。
- 已发布数据：全量同步浏览、点赞、评论、收藏等指标，并生成后续选题分析。
- 模型额度：读取 Aliyun 百炼、Volcengine Ark、SiliconFlow 的免费额度，以及 MiniMax Token Plan 的订阅共享额度，在 GUI 中搜索、排序和选择模型。
- 配图策略：自动每日新闻要求使用 AI 生图，AI 生图失败会让该稿件失败，不会静默改用 Pexels；材料模式可以按配置使用 Pexels 回退；每日 AI 讯息使用本地简报卡片渲染。

## 快速开始

### React 工作台

保留原 `Start-GUI.cmd` 和 CLI。新界面位于 `frontend/`，本地服务为 `apps.web_gui`。
依赖安装后运行以下命令。构建完成后，双击 `Start-Web-GUI.cmd` 会启动本地服务，并用系统默认浏览器打开 `http://127.0.0.1:8765`；浏览器只是工作台界面，平台自动化仍使用项目专用 Chrome profile。

```powershell
Set-Location E:\AI\codex\redbook_workflow
if (-not (Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location frontend
npm ci --cache E:\AI\codex\redbook_workflow\.npm-cache
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m apps.web_gui
```

打开 `http://127.0.0.1:8765`。Node.js 版本要求以 [Vite 官方说明](https://vite.dev/guide/) 为准。依赖安装在 `frontend/node_modules`，缓存显式放在 E 盘，不需要全局安装 npm 包。

工作台只绑定本机，不要直接用于公网部署。额度同步需要显式点击。页面标题右侧的“打开创作者中心”使用项目专用 profile；“账号与设置”也提供头条号专用浏览器入口。不要同时用旧 GUI 和新工作台启动浏览器任务。

Web 工作台包含自动发帖、材料发帖、任务中心、本地草稿处理、平台草稿、删除平台草稿、已发布数据、信源健康、模型与额度、账号与设置十个页面：

- 材料支持单条/多条、粘贴文字/上传 UTF-8 文件；本地图片可填写工作区 `assets` 或 `data/posts` 下的路径通配符。
- 本地草稿可编辑、校验、审核、上传到指定平台及重试失败上传；已保存的小红书草稿可原位更新与回读。
- 平台关联草稿可批量发布；正式删除先按类型、标题、数量预览，再输入“确认删除”。预览十分钟内有效，修改筛选条件后须重新预览。删除平台草稿会保留本地记录。
- 已发布数据页可生成、查看和下载选题分析；信源健康页支持检查、搜索和排序。
- 额度同步支持全部平台或指定平台/模型；配置页支持本机密钥和参数编辑，已有密钥仅返回“已配置/未配置”，空输入保留原值。密钥写入 `.env.gui`，若该文件被 Git 跟踪或未忽略则拒绝保存。

首次启动建议先同步一次额度、确认模型选择，再使用 `--count 1` 验证配置。生成、删除、发布属于真实平台操作；正式执行前应确认平台、标题、图片和正文，并留意短信验证、草稿校验和平台风控。

以下命令以 Windows PowerShell 为例。建议把项目、虚拟环境和 Playwright 浏览器缓存放在非系统盘，例如 E:\AI\codex。项目不会要求在 C 盘安装依赖。

### 1. 获取项目和依赖

    Set-Location E:\AI\codex
    git clone https://github.com/bty3052771076-tech/auto_redbook.git redbook_workflow
    Set-Location E:\AI\codex\redbook_workflow
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    $env:PLAYWRIGHT_BROWSERS_PATH="$PWD\.playwright-browsers"
    .\.venv\Scripts\python.exe -m playwright install chromium

已有本地副本时，直接进入项目目录即可。

如果已经安装依赖，推荐直接运行：

    Set-Location E:\AI\codex\redbook_workflow
    .\Start-Web-GUI.cmd

### 2. 配置模型和费用保护

真实密钥只能放在本地环境变量、`.env.gui` 或其他未跟踪的本地密钥文件中。下面的值全部是占位符，不能替换为真实密钥后提交到 GitHub。GUI 的“配置”页面只显示“已配置/未配置”，不会回显密钥。

Aliyun / DashScope：

    $env:LLM_PROVIDER="aliyun"
    $env:IMAGE_PROVIDER="aliyun"
    $env:DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
    $env:ALIYUN_LLM_MODEL="glm-5.2"
    $env:ALIYUN_IMAGE_MODEL="qwen-image-2.0-pro-2026-06-22"

Volcengine Ark：

    $env:LLM_PROVIDER="volcengine"
    $env:IMAGE_PROVIDER="volcengine"
    $env:VOLCENGINE_API_KEY="YOUR_VOLCENGINE_API_KEY"
    $env:VOLCENGINE_LLM_MODEL="deepseek-v4-pro"
    $env:VOLCENGINE_IMAGE_MODEL="doubao-seedream-5-0-lite-260128"

SiliconFlow：

    $env:LLM_PROVIDER="siliconflow"
    $env:IMAGE_PROVIDER="siliconflow"
    $env:SILICONFLOW_API_KEY="YOUR_SILICONFLOW_API_KEY"
    $env:SILICONFLOW_LLM_MODEL="deepseek-ai/DeepSeek-V3"
    $env:SILICONFLOW_IMAGE_MODEL="Kwai-Kolors/Kolors"

MiniMax Token Plan（订阅额度，不等同于免费额度）：

    $env:LLM_PROVIDER="minimax"
    $env:IMAGE_PROVIDER="minimax"
    $env:MINIMAX_TOKEN_PLAN_API_KEY="YOUR_MINIMAX_TOKEN_PLAN_API_KEY"
    $env:MINIMAX_LLM_MODEL="MiniMax-M3"
    $env:MINIMAX_IMAGE_MODEL="image-01"
    $env:MINIMAX_BILLING_MODE="subscription_only"
    $env:MINIMAX_ALLOW_PAID_CREDITS="0"
    $env:MINIMAX_ALLOW_PAYGO="0"

MiniMax 也可以在 GUI 的配置页面填写 `MINIMAX_TOKEN_PLAN_API_KEY`，或写入项目根目录本地的 `.env.gui`。不要把真实 key 写入 README、命令历史、截图或 Git 已跟踪文件。`minimax-quota` 只读取模型目录和共享订阅额度，不会通过试调用探测额度；平台侧是否会在订阅用尽后转扣已购积分，仍需在账户侧确认。

直接运行 CLI 时，请在当前 PowerShell 会话设置同名环境变量，或创建仅本地使用的 `docs/minimax_api-key.md`：

    api_key=YOUR_MINIMAX_TOKEN_PLAN_API_KEY

`.env.gui` 由 GUI 读取并传给 CLI 子进程，不是 CLI 的隐式配置来源；以上两个位置都已被 `.gitignore` 忽略。

安全检查：提交前运行 `git status --short`、`git ls-files` 和 `git diff --cached --check`。不要提交 `.env.gui`、`data/`、`logs/`、浏览器 Profile、Cookie、额度快照、运行日志、截图、备份目录或任何包含真实 Key/Token 的文件。密钥一旦进入 Git 历史，应立即撤销并重新生成，仅删除当前文件是不够的。

建议始终开启费用保护：

    $env:ALLOW_PAID_LLM_FALLBACK="0"
    $env:SILICONFLOW_FREE_ONLY="1"

auto 模式只选择最新额度快照中已验证、未过期且剩余额度为正的模型。没有可信免费额度时会停止并说明原因，不会自动改用 PPInfra 或其他付费兜底。

### 3. 登录项目专用 Profile

不要使用默认浏览器。项目使用以下目录：

    data/browser/chrome-profile
    data/browser/aliyun-console-profile
    data/browser/volcengine-console-profile
    data/browser/siliconflow-console-profile

小红书自动化使用：

    $env:XHS_CHROME_USER_DATA_DIR="$PWD\data\browser\chrome-profile"
    $env:XHS_CHROME_PROFILE="Default"

额度同步遇到登录要求时，使用项目专用的可见窗口完成登录：

    .\.venv\Scripts\python.exe -m apps.cli aliyun-quota --all-free --login-hold 600 --wait-timeout 120
    .\.venv\Scripts\python.exe -m apps.cli volcengine-quota --all-free --login-hold 600 --wait-timeout 120
    .\.venv\Scripts\python.exe -m apps.cli siliconflow-quota --all-free --login-hold 600 --wait-timeout 120
    .\.venv\Scripts\python.exe -m apps.cli minimax-quota --save-raw

同步完成后，可以用无窗口方式读取已有登录态：

    .\.venv\Scripts\python.exe -m apps.cli sync-quotas --aliyun-model glm-5.2 --volcengine-model deepseek-v4-pro --volcengine-model doubao-seedream-5-0-lite-260128 --headless --login-hold 0 --wait-timeout 120

额度同步不是生成任务的隐式步骤。若你已经在本轮手动同步过额度，可以在生成时使用 `--no-refresh-quotas`，但必须确认快照是当前有效快照；不要盲目复用过期快照。

### 4. 启动 GUI

    .\.venv\Scripts\python.exe -m apps.gui
    .\Start-GUI.cmd

主要页面：自动发帖、材料发帖、本地草稿处理、发布草稿、已发布数据和模型额度。材料发帖独立处理用户提供的文字或文件，发布草稿只扫描创作者中心中尚未发布的草稿。

### 5. 第一次生成的推荐顺序

1. 在“模型与额度”页面确认已有额度快照，选择有剩余额度且已验证的 LLM 与生图模型。
2. 在“账号与设置”页面或项目专用 Profile 中完成小红书登录；不要使用默认浏览器，也不要同时启动多个会占用同一 Profile 的任务。
3. 先用 `--count 1` 或 GUI 的一条任务做小规模验证，确认图文、标题、正文和平台回读均正常。
4. 确认无误后再提高数量。自动每日新闻必须完成 AI 生图；每日 AI 讯息使用本地简报卡片，不会调用普通新闻生图接口。
5. 草稿保存后检查创作者中心中的标题、正文和图片数量，再进行正式发布。程序默认不会把“部分成功”报告成“全部完成”。

### 6. 先生成本地草稿，再上传平台

需要排查内容或模型时，先不打开平台，直接生成本地草稿：

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --keywords "财经产业 公司政策 市场变化" --count 1 --performance-mode speed --no-preflight --no-refresh-quotas
    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --count 1 --performance-mode speed --no-preflight --no-refresh-quotas

生成完成后，程序会在 `data/posts/<post_id>/post.json` 保存本地记录。确认模型、标题、正文和配图没有问题，再使用项目专用 profile 上传：

    $env:XHS_CHROME_USER_DATA_DIR="$PWD\data\browser\chrome-profile"
    $env:XHS_CHROME_PROFILE="Default"
    .\.venv\Scripts\python.exe -m apps.cli run <post_id> --platform xhs --headless --login-hold 0 --wait-timeout 600 --force

`--force` 只跳过本地草稿状态（例如 `draft` 未先审核），不会跳过内容校验、图片校验、平台登录、短信验证或草稿读回。上传成功后，程序会回到小红书草稿箱，读回标题、正文和实际图片数量；读回失败不会报告为成功。

## 生成每日新闻

程序争取约 20N 条原始材料和 10N 条初筛候选，这两个数是优选目标，不是硬性生成门槛。原文补全、事件去重、国内新闻和国际争议配额检查后，能组成 N 条主候选及替补即可进入生成。10条任务优先准备3条替补；最终窗口只有10条合格材料时也允许继续，但后续图文仍须通过审查。默认整批通过后才上传，不会把部分成功报告为全部完成。

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --keywords "财经产业 公司政策 市场变化 / 国际争议事件 外交安全 / 科技产业 芯片 AI" --evaluation-viewpoint "无视角评价" --assets-glob "assets/empty/*" --count 10 --platform xhs --headless --login-hold 0 --wait-timeout 600

每日新闻默认按北京时间自然日 **1 → 2 → 3 → 5天** 逐级扩展，最多包括生成当天及前4天。较新材料优先，够主候选与替补即停止扩展；固定窗口不会自动扩大。GUI提供“自动 / 固定”选择。

- `--lookback-days auto`：显式自动，覆盖环境中的旧固定配置。
- `--lookback-days 2`：固定2天；固定1至5天均合法，包括4天。
- 不传参数：依次读取 `NEWS_LOOKBACK_DAYS`、`CONTENT_LOOKBACK_DAYS`，无配置时自动。旧的7/14天配置会报错，需要改为auto或1至5。

RSS和最新列表在本批任务内复用，支持历史日期的接口只补查新增区间。生成失败后先使用替补，再检查未审核材料和剩余窗口，不重做已合格稿件。速度模式的来源采集预算按整批累计180秒，均衡模式沿用其采集预算；原文补全、模型生成、修复和上传另计。已开始的网络请求须等待自身超时收尾，180秒不是端到端完成保证。

CLI与GUI区分原始、初筛、材料合格、成稿数量，并显示实际窗口、类别缺口及检索预算状态。预算不足时会说明覆盖未完成，不能据此断言五天内没有新闻。本策略不改变每日AI讯息、每日羊毛或材料模式的日期规则。

当前离线回归验收（2026-09-13）：`1111 passed in 261.15s`，并通过 `compileall` 与 `git diff --check`。真实新闻 API、模型额度、AI 生图、浏览器登录和创作者中心回读仍受账号、网络和平台状态影响，应在本机先用 `--count 1` 实测。

## 生成每日 AI 讯息

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --count 1 --platform xhs --headless --login-hold 0 --wait-timeout 600

每日 AI 讯息要求每条有可追溯 URL、发布时间、明确主体、具体动作和事实细节；严格限制为北京时间生成日及前一日，生成前执行历史查重和事件级去重，同一规范化信源最多 2 条。程序会优先模型发布、版本更新、开放权重、API/产品上线等具体事件，拒绝“披露AI产品变化”“动态3”等空泛或占位内容。候选不足时允许少于 8 条，最多保留 20 条高质量动态，不用旧闻硬凑数量。每日 AI 讯息使用本地简报卡片渲染图。

## 材料发帖

材料模式不进行在线新闻检索、关键词筛选或新闻来源日期限制，但必须提供可解析的材料时间。

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --single-news-material-file "data/manual_news/one.md" --material-time "2026-08-20 14:30" --assets-glob "assets/empty/*" --count 1 --platform xhs --headless --login-hold 0 --wait-timeout 600

多条材料使用 --news-materials-file。GUI 中请使用独立的“材料发帖”页面；该页面可以单独选择 LLM、生图平台和模型，模型列表与额度同步结果保持一致。

## 已发布数据和草稿处理

    .\.venv\Scripts\python.exe -m apps.cli update-metrics --headless --login-hold 0 --wait-timeout 600
    .\.venv\Scripts\python.exe -m apps.cli analyze-metrics

正式发布前务必人工确认标题、正文、图片和平台合规要求。

## 测试和安全检查

    .\.venv\Scripts\python.exe -m pytest -q
    .\.venv\Scripts\python.exe -m compileall apps src tests
    git diff --check

前端变更还应执行：

    Set-Location frontend
    npm run build
    Set-Location ..

只要测试或构建失败，就不要推送到 `main`。真实平台登录、额度读取、新闻 API、生图和草稿回读仍需要在你的账号环境中单独验证。

真实平台测试建议先使用 --count 1，确认额度、登录态、图片和草稿读回，再扩大数量。

不要提交真实 API Key、Token、Cookie、密码、签名 URL、.env*、data/、logs/、浏览器 Profile、额度快照、运行日志、本地图片或根目录 *.bak/ 备份。提交前检查：

    git status --short
    git ls-files
    git diff --cached --check

如果密钥曾经进入 Git 历史，不能只删除当前文件；应立即撤销并重新生成密钥，再按仓库安全流程清理历史。

## AI agent 快速交互提示词

将下面这段提示词发送给 AI agent，可以让它按当前项目的完整流程执行。使用前请确认项目 Profile 已登录，额度同步页面已经能够读取免费额度。

我已经完成了额度同步，不需要你再次进行额度同步，重新为我获取截至当前的所有帖子的数据，并以无窗口形式完成以下任务，同时上传到小红书创作者中心的草稿箱中，不要使用我的默认浏览器，使用工作区中配置的专用浏览器，实时为我汇报进度：
1、为我分析我今天要生成哪些 每日新闻，并生成10条，确保AI生成的图和内容与评价相符合，你需要使用有额度的LLM模型和生图模型，至少需要包含两条国际上热度较高的争议事件。
2、生成今日的 每日AI讯息，并需要进行查重，并且保证信源的多样性。
## License

本仓库主要用于个人本地自动化和工程案例研究。使用第三方平台、模型和新闻内容时，请遵守对应平台的服务条款、版权要求和当地法律法规。
## Speed-first mode

The default scheduler is `balanced`. Use `--performance-mode speed` when shorter wall time is more important than the widest discovery pass:

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --keywords "AI模型发布" --count 10 --performance-mode speed --headless --no-preflight --login-hold 0 --wait-timeout 600
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --count 1 --performance-mode speed --headless --no-preflight --login-hold 0 --wait-timeout 600
```

Speed mode uses a bounded completion-first coordinator and parallel AI search discovery. LLM and image generation remain in separate queues: MiniMax LLM uses up to five workers when the run is explicitly locked to MiniMax, other LLM providers use up to two, and image generation uses up to two. Xiaohongshu upload remains serial. It does not bypass freshness, deduplication, source-quality, image-quality, subscription-only, or remote readback checks.

The mode is also available as `运行模式` in the GUI automatic-posting page. Use `balanced` when source coverage is more important than latency. Runtime events are stored under `data/runs/<run_id>/events.jsonl`; sensitive key names and values are excluded from telemetry.
