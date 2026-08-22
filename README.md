# Auto Redbook

Auto Redbook 是一个运行在 Windows 本地的中文内容生产与草稿分发工具。它从多种新闻和 AI 官方信源采集材料，生成图文内容，保存到小红书创作者中心和今日头条草稿箱，并同步小红书已发布内容的互动数据。

## 当前能力

- 每日新闻：从多信源候选池采集约 20x 原始材料，按时效、热度、关键词、来源多样性和质量筛选，再生成标题、正文、评价和配图。
- 每日AI讯息：优先读取模型厂商官网、官方公告、官方 GitHub 和官方社交账号，生成至少 8 条带发布时间和来源的简报卡片。
- 材料发帖：支持单条/多条文件，也支持 GUI 直接粘贴文字；材料模式需要材料时间，但不套用在线新闻的日期窗口。
- 多平台草稿：支持小红书、今日头条或两个平台；保存后会回到创作者中心进行标题、正文和图片读回验证。
- 已发布数据：全量同步浏览、点赞、评论、收藏等指标，并生成后续选题分析。
- 免费额度：读取 Aliyun 百炼、Volcengine Ark 和 SiliconFlow 的官方控制台或模型列表信息，在 GUI 中搜索、排序和选择模型。
- 配图策略：普通新闻优先 AI 生图，失败时可以回退 Pexels；每日 AI 讯息使用本地简报卡片渲染。

## 快速开始

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

### 2. 配置模型和费用保护

真实密钥只能放在本地环境变量、.env 文件或未跟踪的本地 key 文件中。下面的值全部是占位符，不能替换为真实密钥后提交到 GitHub。

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

同步完成后，可以用无窗口方式读取已有登录态：

    .\.venv\Scripts\python.exe -m apps.cli sync-quotas --aliyun-model glm-5.2 --volcengine-model deepseek-v4-pro --volcengine-model doubao-seedream-5-0-lite-260128 --headless --login-hold 0 --wait-timeout 120

### 4. 启动 GUI

    .\.venv\Scripts\python.exe -m apps.gui
    .\Start-GUI.cmd

主要页面：自动发帖、材料发帖、本地草稿处理、发布草稿、已发布数据和模型额度。材料发帖独立处理用户提供的文字或文件，发布草稿只扫描创作者中心中尚未发布的草稿。

## 生成每日新闻

程序会先获取约 20N 条原始候选，至少争取 10N 条合格候选，再执行去重、来源多样性和 LLM 审校。默认是完整批次策略，任一条未通过质量检查时不会上传半批结果。

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --keywords "财经产业 公司政策 市场变化 / 国际争议事件 外交安全 / 科技产业 芯片 AI" --evaluation-viewpoint "无视角评价" --assets-glob "assets/empty/*" --count 10 --platform xhs --headless --login-hold 0 --wait-timeout 600

每日新闻只使用严格的新鲜日期窗口。候选不足时，CLI 和 GUI 会显示具体信源、候选数、过滤数和停止原因，不会用旧新闻凑数。

## 生成每日 AI 讯息

    .\.venv\Scripts\python.exe -m apps.cli auto --title "每日AI讯息" --count 1 --platform xhs --headless --login-hold 0 --wait-timeout 600

每日 AI 讯息默认至少生成 8 条，要求每条有可追溯 URL 和发布时间，优先选择官方模型厂商来源；同一规范化信源最多 2 条，生成前执行历史查重。官方来源不足、国内/国外模型配额不足或内容质量不达标时，程序会停止并说明原因，不生成“动态3”“动态5”等占位内容。每日 AI 讯息使用本地简报卡片渲染图，普通新闻才调用 AI 生图模型。

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

真实平台测试建议先使用 --count 1，确认额度、登录态、图片和草稿读回，再扩大数量。

不要提交真实 API Key、Token、Cookie、密码、签名 URL、.env*、data/、logs/、浏览器 Profile、额度快照、运行日志、本地图片或根目录 *.bak/ 备份。提交前检查：

    git status --short
    git ls-files
    git diff --cached --check

如果密钥曾经进入 Git 历史，不能只删除当前文件；应立即撤销并重新生成密钥，再按仓库安全流程清理历史。

## AI agent 快速交互提示词

将下面这段提示词发送给 AI agent，可以让它按当前项目的完整流程执行。使用前请确认项目 Profile 已登录，额度同步页面已经能够读取免费额度。

> 重新为我获取截至当前的所有帖子的数据，并以无窗口形式完成以下任务，同时上传到小红书创作者中心的草稿箱中，不要使用我的默认浏览器，使用工作区中配置的专用浏览器，实时为我汇报进度：
>
> 1、为我分析我今天要生成哪些 每日新闻，并生成10条，确保AI生成的图和内容与评价相符合，你需要使用有额度的LLM模型和生图模型（生图模型使用额度剩余较多的模型，额度同步时可以弹出页面让我登录，尽量不要使用我充值的金额/代金券），至少需要包含两条国际上热度较高的争议事件。
>
> 2、生成今日的 每日AI讯息，并需要进行查重，并且保证信源的多样性。
>
> 执行前必须重新确认已发布数据和免费额度快照，不得直接复用上一次额度快照；优先使用已验证的免费模型，禁止自动切换到付费 PPInfra；每个步骤都要输出当前进度和可操作的错误原因。所有草稿保存后必须在小红书创作者中心读回标题、正文和图片数量，确认成功后再报告完成。

## License

本仓库主要用于个人本地自动化和工程案例研究。使用第三方平台、模型和新闻内容时，请遵守对应平台的服务条款、版权要求和当地法律法规。
