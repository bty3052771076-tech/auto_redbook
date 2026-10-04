# Auto Redbook

> 当前公开版本：2026-09-17。项目面向 Windows 本地运行，建议将项目、虚拟环境和浏览器缓存放在非系统盘。

Auto Redbook 是一个运行在 Windows 本地的中文内容生产与草稿分发工具。它从多种新闻和 AI 官方信源采集材料，生成图文内容，保存到小红书创作者中心和今日头条草稿箱，并同步小红书已发布内容的互动数据。

> 当前版本以本地运行和人工复核为前提。它不会替你绕过平台登录、短信验证、风控或发布审核，也不会把 API Key 自动上传到 GitHub。

## 当前能力

- 每日新闻：从多信源候选池采集约 20x 原始材料，按时效、热度、关键词、来源多样性和质量筛选，再生成标题、正文、评价和配图。
- 每日AI讯息：优先读取模型厂商官网、官方公告、官方 GitHub 和官方社交账号；只保留北京时间生成日及前一日的可追溯信息，按事件级查重和信源上限筛选，最终动态数量按高质量候选自动决定，范围为 1–20 条，不再硬凑 8 条。
- 材料发帖：支持单条/多条文件，也支持 GUI 直接粘贴文字；材料模式需要材料时间，但不套用在线新闻的日期窗口。
- 多平台草稿：支持小红书、今日头条或两个平台；保存后会回到创作者中心进行标题、正文和图片读回验证。
- 已发布数据：全量同步浏览、点赞、评论、收藏等指标，并生成后续选题分析。
- 模型额度：读取 Aliyun 百炼、Volcengine Ark、SiliconFlow 的免费额度，以及 MiniMax Token Plan 的订阅共享额度，在 GUI 中搜索、排序和选择模型。
- 智能体对话工作台：独立于自动发帖页，通过自然语言解析出指定栏目、数量、平台和交付方式，再复用现有 LangGraph 执行图；主控、写稿、生图角色分别读取模型绑定。
- World Monitor 全球事件关注图：按需读取本地 World Monitor 新闻摘要，按北京时间、独立信源和已核验坐标生成固定尺寸地图；覆盖不足时只保存本地报告，不自动上传。
- 配图策略：自动每日新闻要求使用 AI 生图，AI 生图失败会让该稿件失败，不会静默改用 Pexels；材料模式可以按配置使用 Pexels 回退；每日 AI 讯息使用本地简报卡片渲染。

## 快速开始

### 本机目录与工具

工作流的代码、前端和 Python 环境都在本项目内。World Monitor、RSSHub、AIHOT、OpenCodex 软件包及 PostgreSQL 二进制的本地副本放在 `tools/`；原来的工具目录保留，不会自动删除。副本包含已有依赖和构建产物，不需要在 C 盘安装内容。部署脚本：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/provision_local_tools.ps1`。

数据仍在本项目的 `data/`、`assets/`，API Key 仍在被忽略的 `.env.gui`。独立智能体的数据仍在 `E:\AI\codex\redbook_runtime`。两个程序的 OpenCodex 并发锁及请求状态继续共享，避免重复生图。系统 Python、Node.js、Chrome 和已授权的 OpenCodex 服务仍使用本机环境。

`Start-RSSHub.cmd` 启动本项目的 RSSHub 副本。AIHOT 使用 `scripts/manage_aihot.ps1 -Action start -Worker`，结束后使用 `-Action stop`；其数据继续在 `E:\AI\codex\AIHOT-data`。两个程序使用同一个 AIHOT 数据库，不能同时启动两份 AIHOT 服务。PostgreSQL 管理入口为 `scripts/manage_postgresql.ps1`，不自动初始化或搬动旧数据库。

### OpenCodex / ChatGPT 订阅生图

可在本地 `.env.gui` 启用 `OPENCODEX_IMAGE_ENABLED=1`，在工作台选择 `OpenCodex / ChatGPT订阅` 的 `gpt-image-2`；终端使用 `IMAGE_PROVIDER=opencodex`。适配器仅调用本机订阅图片路由，最多 2 并发，成功图片缓存复用；不确定请求不会自动重发。`OPENCODEX_IMAGE_FALLBACK=minimax` 允许普通生图转用 MiniMax Token Plan，禁止付费 API/paygo。

AI 福利可使用 `WOOL_IMAGE_MODE=reference_edit`，由 `assets/wool/参考原图` 的构图和 `assets/wool/人设图` 的实际活动提供商人设进行双图编辑。双图编辑没有经过等价验证的 MiniMax 降级；缺人设或编辑不可用时明确报错，不用普通插画冒充。OpenCodex 更新后若代码检查不通过，需要重新验证，不会盲目继续。详见本地 `docs/plans/2026-10-03-opencodex-subscription-image-integration.md`。

同时使用旧工作流与独立智能体时，两边本地配置应指向相同的 `OPENCODEX_IMAGE_LOCK_DIR` 和 `OPENCODEX_IMAGE_STATE_DIR`，共享两路并发上限和不确定请求保护。独立部署需将参考图及人设图复制到独立运行区，素材相对路径以 `REDBOOK_RUNTIME_ROOT` 为基准，不依赖旧项目目录。

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

Web 工作台包含智能体、全球事件关注图、自动发帖、材料发帖、任务中心、本地草稿处理、平台草稿、删除平台草稿、已发布数据、信源健康、模型与额度、账号与设置十二个页面：

- 材料支持单条/多条、粘贴文字/上传 UTF-8 文件；本地图片可填写工作区 `assets` 或 `data/posts` 下的路径通配符。
- 本地草稿可编辑、校验、审核、上传到指定平台及重试失败上传；已保存的小红书草稿可原位更新与回读。
- 平台关联草稿可批量发布；正式删除先按类型、标题、数量预览，再输入“确认删除”。预览十分钟内有效，修改筛选条件后须重新预览。删除平台草稿会保留本地记录。
- 已发布数据页可生成、查看和下载选题分析；信源健康页支持检查、搜索和排序。
- 额度同步支持全部平台或指定平台/模型；配置页支持本机密钥和参数编辑，已有密钥仅返回“已配置/未配置”，空输入保留原值。密钥写入 `.env.gui`，若该文件被 Git 跟踪或未忽略则拒绝保存。

首次启动建议先同步一次额度、确认模型选择，再使用 `--count 1` 验证配置。生成、删除、发布属于真实平台操作；正式执行前应确认平台、标题、图片和正文，并留意短信验证、草稿校验和平台风控。

### 智能体对话工作台

点击左侧“智能体”进入独立对话页面。这里不再把智能调度开关嵌在自动发帖表单中；自动发帖和材料发帖仍保持原来的字段与流程。

使用步骤：

1. 在“模型与供应商”中确认智能体主控、写稿、生图三个角色的绑定；已完成本轮额度同步时，直接使用当前绑定，不会由智能体再次同步额度。
2. 在输入框明确写出栏目、数量和目标平台，例如 `用 MiniMax 生成3条每日新闻和1篇每日AI讯息，保存到小红书草稿`。
3. 查看右侧“本次计划”，确认栏目、数量、平台、运行模式和交付方式后点击“执行计划”。明确包含“只生成/不要上传”时只生成本地稿，否则按计划保存到平台草稿。
4. 运行中可在对话页查看事件，也可打开“任务中心”查看完整日志；平台上传保持串行，不会因为对话入口产生第二套上传通道。

### 记忆、Skills 与工具

- 智能体右侧“记忆与工具”显示 PostgreSQL 会话记忆、MCP 和 Skills 状态。`知识库 ready` 只表示数据库/schema 可用；还要看 `index_ready`。向量索引未就绪时，智能体会阻止依赖历史查重的生成，不会降级为 SQLite、内存或仅关键词搜索。
- 使用现有 E 盘知识库前可先运行只读状态检查：

  ```powershell
  .\.venv\Scripts\python.exe -m apps.cli knowledge-status
  .\.venv\Scripts\python.exe -m apps.cli knowledge-index
  ```

  `knowledge-status` 在数据库或向量索引未就绪时会返回非零状态；`knowledge-index` 会从本地数据增量入库并建立向量索引，首次运行可能从 Hugging Face 下载 FastEmbed 权重，默认缓存为工作区 E 盘 `data/models/fastembed/`，不调用付费模型。`knowledge-migrate` 会先备份现有 E 盘 PostgreSQL 再迁移 schema，不是日常启动命令；不要删除或重建现有数据目录。
- Skill 模式默认“关闭”。可切换“按任务自动选择”，或手动勾选最多 3 个 Skill；执行计划会冻结所选版本。Skill 正文仅作为不可信的写作方法参考，不能执行其中命令、改变事实核验、费用限制、工具权限或平台发布策略。
- 从工作区开发 Skill 导入到运行时目录：

  ```powershell
  .\.venv\Scripts\python.exe -m src.agent.skills_cli import .agents/skills/@user_f42753f5/ai-tech-hot
  ```

  可通过 `python -m src.agent.skills_cli list` 检查，GUI 能力面板也会显示可用项。导入只复制并校验文件，不会运行 Skill 中的脚本。
- MCP 可按需实测，不会开机常驻：

  ```powershell
  .\.venv\Scripts\python.exe -m src.agent.mcp_manager list
  .\.venv\Scripts\python.exe -m src.agent.mcp_manager call runtime_status --args "{}"
  ```

- 会话压缩只生成版本化摘要，原始消息仍保存在 PostgreSQL。摘要仅延续偏好和未完成事项，不是新闻事实或来源；执行新任务时当前指令与当轮核验材料优先。摘要生成需达到阈值后手动触发，真实模型调用可能消耗所配置的 MiniMax 订阅额度。
- 压缩快照版本和选用的 Skill 名称/版本会被冻结在任务计划与检查点中；常规工作流进度保存在任务事件/运行检查点里。MCP 当前用于能力检查及显式诊断调用，尚未交给模型在每次内容生成中自主选择；诊断命令结果显示在终端。运行检查点在 `data/runs/agent/<run_id>/`，任务计划在 `data/web_gui/conversations/<conversation_id>/plans/`。其中计划文件可能含有冻结后的 Skill 正文，应按本地运行数据保管，不上传到公开仓库。

智能体首版接受五类栏目：`每日新闻`、`每日AI讯息`、`每日羊毛`、`每日我去`、`今日全球事件关注图`。它不会执行聊天中的 shell、任意文件路径或任意外部写入指令。日期、查重、内容完整性、图像质量、模型费用策略和平台登录仍由程序门禁负责，不能靠一句提示词绕过。

中断后，任务中心会保留运行记录和智能体检查点。恢复只重用已经生成的稿件，并跳过内容版本与平台结果均已完成的条目；未知的平台写入结果不会盲目重传。旧检查点入口仍支持 CLI：

    .\.venv\Scripts\python.exe -m apps.cli agent --job-plan-file data\web_gui\conversations\<conversation>\plans\<plan>.json --resume-from data\runs\agent\<run_id>\checkpoint.json --no-refresh-quotas --headless --login-hold 0

### 全球事件关注图

该页面和智能体都默认不启动 World Monitor。先在本地 PowerShell 会话配置受控地址或项目目录，再显式启用：

```powershell
$env:GLOBAL_MAP_ENABLED="1"
$env:WORLDMONITOR_ENABLED="1"
$env:WORLDMONITOR_BASE_URL="http://127.0.0.1:3000"
# 如果需要由程序按需启动本地 clone，再配置目录并打开自动启动
$env:WORLDMONITOR_DIR="E:\AI\codex\worldmonitor"
$env:WORLDMONITOR_AUTO_START="1"
```

可以在 GUI 左侧进入“全球事件关注图”，或使用：

```powershell
.\.venv\Scripts\python.exe -m apps.cli global-map --generate-only --headless
```

`--generate-only` 只保存 `data/global_map/` 下的地图和证据快照；正式提交平台草稿时去掉该参数。World Monitor 返回陈旧覆盖、事件定位不足或服务不可用时，程序会给出具体错误并停止上传，不会把不足数据伪装成全球热力图。

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

此前离线回归验收（2026-09-13）：`1111 passed in 261.15s`。智能体首版另完成专项与全量回归；真实新闻 API、模型额度、AI 生图、浏览器登录和创作者中心回读仍受账号、网络和平台状态影响，应在本机先用 `--count 1` 实测。

## 生成每日 AI 讯息

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --count 1 --platform xhs --headless --login-hold 0 --wait-timeout 600

每日 AI 讯息要求每条有可追溯 URL、发布时间、明确主体、具体动作和事实细节；严格限制为北京时间生成日及前一日，生成前执行历史查重和事件级去重，同一规范化信源最多 2 条。程序会优先模型发布、版本更新、开放权重、API/产品上线等具体事件，拒绝“披露AI产品变化”“动态3”等空泛或占位内容。候选不足时允许少于 8 条，最多保留 20 条高质量动态，不用旧闻硬凑数量。每日 AI 讯息使用本地简报卡片渲染图。

### 本地 AIHOT 信源（可选）

开源 AIHOT 安装在 `E:\AI\codex\AIHOT`，使用独立的 `E:\AI\codex\AIHOT-data` 和本机 PostgreSQL 5434 端口。它的开源种子仅包含演示信源，不含线上站点的完整生产数据。首次部署已完成；需要使用时在 PowerShell 中启动，结束后停止，不随 Windows 开机启动：

    & 'E:\AI\codex\AIHOT\scripts\local-stack.ps1' start -Worker
    # 浏览器：http://127.0.0.1:8768  API：http://127.0.0.1:8767/api/v1/items?mode=all&window=7d&by=published&limit=100
    & 'E:\AI\codex\AIHOT\scripts\local-stack.ps1' stop

原工作区和独立智能体的本地 `.env.gui` 均配置了 `AI_DIGEST_LOCAL_AIHOT_BASE_URL=http://127.0.0.1:8767`；没有启动 AIHOT 时该信源会报告连接错误，其余信源仍可继续。程序只解析本地 `/api/v1/items` 中公开且通过 AIHOT 基本资格检查的条目，要求可追溯的原始 URL、明确发布时间、具体标题和摘要，标记为**聚合线索**而非“官方已核验”；AIHOT 的站内精选分数不是本项目的最终选稿标准。原始 URL 不可用时不会用 AIHOT 卡片链接冒充新闻来源。原有两日时效、历史查重和每信源数量上限仍然生效。

AIHOT 的 `.env`、PostgreSQL 凭据和 MiniMax Key 只保存在 E 盘本地，不提交 Git。它的模型调用总量由独立数据库预算限制；默认不配置 Jina 等额外付费回退服务。

## 材料发帖

材料模式不进行在线新闻检索、关键词筛选或新闻来源日期限制，但必须提供可解析的材料时间。

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --single-news-material-file "data/manual_news/one.md" --material-time "2026-08-20 14:30" --assets-glob "assets/empty/*" --count 1 --platform xhs --headless --login-hold 0 --wait-timeout 600

多条材料使用 --news-materials-file。GUI 中请使用独立的“材料发帖”页面；该页面可以单独选择 LLM、生图平台和模型，模型列表与额度同步结果保持一致。

## 已发布数据和草稿处理

    .\.venv\Scripts\python.exe -m apps.cli update-metrics --headless --login-hold 0 --wait-timeout 600
    .\.venv\Scripts\python.exe -m apps.cli analyze-metrics

正式发布前务必人工确认标题、正文、图片和平台合规要求。

智能体现在也可以管理小红书创作者中心中已经存在的图文草稿。它会使用项目专用 profile 读取草稿列表，逐篇打开编辑器读取标题、正文和图片，生成可审计快照，再按可读性、图片完整性、保存时间和已发布内容指纹进行审查。读取失败或列表不完整时不会把结果当作空草稿箱，也不会继续公开发布。

只读审查示例：

    .\.venv\Scripts\python.exe -m apps.cli manage-drafts --mode review --draft-type image --headless --login-hold 0 --wait-timeout 600

最多审查 5 条、标题过滤并保存本次检查点：

    .\.venv\Scripts\python.exe -m apps.cli manage-drafts --mode review --max-items 5 --title-contains "每日AI" --run-id ai-review-1 --headless --login-hold 0

公开发布必须显式使用 `--yes`。程序只会选择完整、通过审查的草稿，并通过现有小红书串行发布链路逐条验证；发布后的平台结果不确定时会停止该条，不会盲目重发：

    .\.venv\Scripts\python.exe -m apps.cli manage-drafts --mode publish --max-items 5 --yes --headless --login-hold 0 --wait-timeout 600

快照、审查结果和检查点保存在 `data/runs/draft_management/<run_id>/`。Web 智能体中可以直接输入“检查小红书创作者中心现有草稿，先审查不要发布”或“从小红书草稿箱筛选最多 2 条并发布”；第二种指令会在计划中明确显示公开发布动作。

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

## AI鸡蛋参考图库

Web GUI 在“自动发帖 → 每日羊毛”中提供“AI鸡蛋参考图库”；独立智能体在左侧“AI鸡蛋图库”中提供同一功能。

1. 在“候选图”选择风格、数量，点击“获取候选”，或浏览已经下载的 Danbooru 批次。
2. 点图片查看大图和作者来源；确认人物成年、非露骨及使用权限后“入选参考原图”。仅网站标签或程序视觉审查不代表人工批准。排除只改变状态，不删除原图。
3. 在“参考原图”可以指定一张图，或按日期和厂商自动选择。“人设图”仍使用 `assets/wool/人设图` 的厂商图片。
4. 生成 AI鸡蛋/AI福利（每日羊毛）时，有人工入选图便自动使用 ChatGPT 订阅双图编辑：参考原图提供姿势和构图，人设图决定人物形象。不会切换到付费 API，也不会降级丢弃人设图。

人工命令也可用：`python -m apps.cli wool-library list`、`wool-library fetch --count 10 --style mixed`、`wool-library review <图片ID> --decision approve --adult-confirmed --non-explicit-confirmed --rights-confirmed`、`wool-library select <图片ID>`。不带 ID 的 `select` 恢复按日期自动选择。独立工具入口是 `python -m redbook_tools wool-library ...`。

候选在 `assets/wool/候选原图`，入选副本在 `assets/wool/参考原图`，人工决定在 `assets/wool/reference-library.json`；以上均为本地忽略文件。新旧程序运行区分开，不会自动共享批准状态。详见 `docs/plans/2026-10-03-wool-reference-library-design.md`。
