# Auto Redbook

Auto Redbook 是一个运行在本地的中文内容生产与多平台草稿分发工具，当前支持小红书创作者中心和头条号创作平台。它负责采集和筛选新闻、生成图文内容、按平台调整呈现形式、保存并回读草稿、同步小红书已发布数据，并用实际互动数据辅助下一轮选题。

当前版本的主要能力：

- `每日新闻`：从多来源候选池中按检索关键词、时效性、热度和来源多样性筛选新闻，生成标题、正文、评价和配图。
- `每日AI讯息`：采集国内外模型、版本、API、开发工具、开源项目和基础设施动态，生成带发布时间与来源链接的多页简报。
- 新闻材料模式：支持单条材料直生成和多条材料候选池筛选。
- 多平台草稿：同一条冻结内容可保存到小红书、今日头条或两边；两个创作平台共用工作区浏览器 Profile，并分别执行草稿回读验证。
- 已发布数据：全量同步已发布笔记的浏览、点赞、评论、收藏等指标，并生成选题分析。
- 模型额度：通过 Aliyun 百炼、Volcengine Ark 官方控制台页面和 SiliconFlow 模型列表 API/控制台页面读取可见免费额度/用量，在 GUI 中搜索、排序和切换模型。
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

Ark 控制台额度表使用用户侧名称，OpenAI 兼容接口则可能要求带日期的 API ID。程序会自动处理当前已验证映射，例如 `glm-5.2 -> glm-5-2-260617`、`deepseek-v4-flash -> deepseek-v4-flash-260425`、`deepseek-v4-pro -> deepseek-v4-pro-260425`。GUI 和 CLI 仍显示控制台名称；自动模式只选额度为正且已验证可调用的模型。

SiliconFlow（硅基流动）示例：

```powershell
$env:LLM_PROVIDER="siliconflow"
$env:IMAGE_PROVIDER="siliconflow"
$env:SILICONFLOW_API_KEY="YOUR_SILICONFLOW_API_KEY"
$env:SILICONFLOW_LLM_MODEL="deepseek-ai/DeepSeek-V3"
$env:SILICONFLOW_IMAGE_MODEL="Qwen/Qwen-Image"
```

还支持 `ppinfra` 和 `auto` LLM 提供商。`auto` 采用额度快照驱动的免费优先策略：只选择最新快照中 `status=available`、`remaining>0`、未过期且已配置 Key 的阿里云、火山引擎或硅基流动模型，不会把模型目录、默认模型或未知额度误当成免费额度，也默认不会调用 PPInfra。需要 PPInfra 时，请显式选择 `LLM_PROVIDER="ppinfra"`；只有设置 `ALLOW_PAID_LLM_FALLBACK=1`，它才具备付费兜底资格。GUI 默认使用 `auto`，图片来源也可选择 `auto`，由同一次预检选择余额充足的生图模型。模型、图片和可选新闻源凭据仅通过本地环境变量或本地未跟踪文件配置；不要把真实端点、密钥或登录态写入仓库。

### 4. 登录浏览器 Profile

小红书和头条号共用同一份内容平台 Profile；Aliyun 和 Volcengine 各自使用独立 Profile。这样无需重复维护创作平台登录环境，同时不会把云控制台登录态混入发布 Profile：

```powershell
data/browser/chrome-profile
data/browser/aliyun-console-profile
data/browser/volcengine-console-profile
```

首次上传前，使用 GUI 顶部的小红书或头条号打开按钮，也可以运行对应快捷入口：

```powershell
.\Open-Toutiao-Creator.cmd
```

小红书也可直接打开共享 Profile：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  "--user-data-dir=$PWD\data\browser\chrome-profile" `
  "https://creator.xiaohongshu.com/publish/publish?target=image"
```

两个创作平台不要求同时登录，但登录态都保存在 `data/browser/chrome-profile`。从 GUI 的头条号按钮或 `Open-Toutiao-Creator.cmd` 打开时，会在本机 `127.0.0.1:9223` 建立自动化连接，登录页面可以保持打开；后续 GUI/CLI 命令会自动发现该连接，新开自己的标签页，完成后只关闭该标签页。端口只绑定回环地址，不对外网开放，可用 `TOUTIAO_CDP_PORT` 修改。若使用其他命令手工打开 Profile 且没有调试端口，则需在无窗口运行前关闭该 Chrome 窗口以释放 Profile 锁。额度首次同步失败时，在 GUI 分别打开 Aliyun/Volcengine 登录入口，完成登录并关闭窗口，然后运行 `sync-quotas`。

头条号首次使用还必须开通文章发布权益。若后台显示“请完善账号信息”，请进入账号完善页选择“大陆作者”，再使用今日头条 App 的“我的 → 设置 → 扫一扫”完成作者信息。程序会在写入标题、正文和图片前检查这项权益；未开通时直接返回中文指引和非零退出码，不会留下半成品。

### 5. 启动 GUI

```powershell
.\.venv\Scripts\python.exe -m apps.gui
```

或者运行：

```powershell
.\Start-GUI.cmd
```

GUI 的“自动发帖”页面按内容与来源、材料模式、本次模型、运行设置组织：可在实时检索、单条材料和多条材料之间切换，只显示当前真正生效的输入；右侧“任务监控”批量显示步骤日志和模型额度。“已发布数据”页面执行全量同步和分析。

### 6. 首次生成一条草稿

完成模型配置和目标创作平台登录后，推荐先生成一条 `每日新闻` 验证整条链路。命令会自动预检已发布数据与两个云平台的免费额度，选择可用模型，最后只保存到草稿箱，不会正式发布：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --keywords "财经产业 公司政策 市场变化" `
  --evaluation-viewpoint "无视角评价" `
  --assets-glob "assets/empty/*" `
  --count 1 `
  --platform xhs `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

将 `--platform xhs` 改为 `toutiao` 可只保存到今日头条，改为 `both` 可依次保存到两个平台。头条号首次使用请运行 `Open-Toutiao-Creator.cmd`，在共享 Profile 中完成登录并保持该 Chrome 窗口打开；CLI 会自动探测本机 `TOUTIAO_CDP_PORT`（默认 `9223`），也可显式设置 `TOUTIAO_CDP_URL`。平台偶尔会要求绑定手机号短信校验，该校验不能绕过；程序会跳过失真的预检标志，以真实保存响应为准。连接可见会话后若收到官方 `7050`，程序默认显示并等待 600 秒官方验证码窗口，验证成功后在原编辑页自动重试；可用 `TOUTIAO_SMS_WAIT_SECONDS` 调整等待。同一持久化 Profile 验证成功后通常可继续复用会话。命令最终只有目标平台均出现 `saved_draft`，并完成标题、正文、唯一图片数与封面回读，才表示本次草稿实际写入成功。

## 常用命令

`关键词`只用于扩展检索查询和筛选候选新闻，不是写作指令。正文、标题和评价的专业新闻写法由程序内部规则统一控制；CLI 的主参数为 `--keywords`，旧的 `--prompt` 仍可用于兼容已有脚本。

### 一条命令的完整流程

`auto` 默认启用统一预检和质量流水线，不需要先手工运行其他命令：

```text
检查/同步已发布数据
  -> 检查/同步阿里云、火山引擎和硅基流动免费额度
  -> 选择有正数免费额度的 LLM、生图模型和视觉模型
  -> 采集、日期过滤、相关性筛选和去重
  -> 生成文案与图片
  -> 来源日期、简体中文、批次/历史重复和图片有效性检查
  -> VLM 图文一致性复核；普通新闻失败时按反馈有限重画，AI 简报卡片不自动重绘
  -> 按 --platform 保存小红书、今日头条或两个平台的草稿
  -> 分别进入目标平台草稿箱，回读标题、正文和图片数量
```

已发布数据快照默认复用 24 小时，额度快照默认复用 2 小时；过期才访问平台同步。可用 `--metrics-max-age-hours` 和 `--quota-max-age-hours` 调整。无窗口额度刷新默认最多等待 60 秒，可用 `AUTO_QUOTA_SYNC_TIMEOUT_S` 在 10 至 300 秒之间调整；控制台临时没有返回数值时，程序只会回退到 24 小时内仍为正数的有效快照并明确警告，不会把未知额度当作免费。同步已发布数据失败但存在旧快照时会带警告继续；没有可信免费额度时会在模型调用前阻断。`--no-preflight` 只用于离线单元测试或明确的高级调试，不建议日常生成使用。

每个阶段都会在 CLI 和 GUI 输出当前步骤、完成数、目标数和可操作错误。GUI 的“发布平台”可选择小红书、今日头条或两者。自动流程只保存草稿，不正式发布；生成成功但任一目标平台上传、回读或数量不完整时，CLI 最终阶段为 `failed` 并返回非零退出码，不会把部分结果报告成成功。

### 生成每日新闻

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日新闻" `
  --keywords "财经产业 公司政策 市场变化 / 国际冲突 外交安全 / 硬科技 芯片 AI" `
  --evaluation-viewpoint "无视角评价" `
  --assets-glob "assets/empty/*" `
  --count 10 `
  --platform both `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

生成 `x` 条草稿时，程序会先跨信源积累更大的原始候选池，再去重、按关键词匹配和新闻质量筛选。默认候选目标约为 `20x`，至少尽量达到 `10x`；来源耗尽或时间窗内素材不足时，会输出各阶段数量和停止原因。

#### 批次完成规则

批量 `每日新闻` 默认采用“完整批次才上传”：生成 `N` 条时，先尝试收集约 `20N` 条原始材料，并要求至少有 `10N` 条通过日期和关键词筛选的候选，再使用一次 LLM 批量审校进行重排、去重与国内新闻配额检查。只有 `N` 条文案和配图都通过校验，才开始保存到所选平台草稿箱。

候选、文案或配图不足时，终端和 GUI 会显示信源名称、候选数量、当前草稿序号与可操作原因，并且默认不上传部分结果。仅在需要人工保留部分草稿时，才使用高级参数 `--allow-partial`。

### 生成每日AI讯息

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto `
  --title "每日AI讯息" `
  --count 1 `
  --platform both `
  --headless `
  --login-hold 0 `
  --wait-timeout 600
```

每日 AI 讯息默认要求至少 8 条合格动态，并优先满足国内模型和国外 AI 资讯配额。所有条目必须有可追溯来源和真实发布时间；不满足时间、来源或内容门禁时宁可少生成，也不会用旧消息补数。

自动回溯模式只进行一次最大 14 天的网络采集，再在同一份去重候选池上依次做北京时间 3、7、14 天本地过滤，避免重复抓取全部信源。程序从合格候选中冻结恰好 8 条，目标为至少 6 条官方来源，并保证至少 3 条国内模型资讯和 3 条国外 AI 资讯，再让 LLM 按原顺序逐条改写为简体中文。固定 `--lookback-days` 时官方来源门禁保持严格；自动模式只有在 3/7/14 天全部耗尽且国内/国外/总量约束仍满足时，才允许使用官方来源最多、日期最新的一组并记录降级警告。LLM 只返回紧凑的标题、摘要、URL 和标签；发布时间、厂商及来源由程序从冻结记录恢复。若模型返回损坏 JSON 或条数不对，会在同一条 CLI 命令内自动重试一次，仍失败才启用不改变来源和日期的配额安全兜底。

### 回溯天数

普通 `每日新闻` 默认且最多使用 2 个北京时间自然日，即发帖当天和前一天；`--lookback-days` 只接受 `1` 或 `2`，环境变量也不能放宽，候选不足时停止并说明近期信源不足。单条人工材料同样必须提供可解析且位于两日内的来源发布时间。`每日AI讯息` 仍可用 `--lookback-days N` 固定窗口；留空时按 `3 -> 7 -> 14` 天自动扩展。

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

.\.venv\Scripts\python.exe -m apps.cli siliconflow-quota `
  --model deepseek-ai/DeepSeek-V3 `
  --model Qwen/Qwen-Image `
  --login-hold 600 `
  --wait-timeout 120 `
  --save-raw
```

同步三个平台并更新 GUI 使用的快照：

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

# 将一条已审批或已在小红书保存/发布的本地内容复制到头条号草稿箱
# 若 Open-Toutiao-Creator.cmd 正在运行，CLI 会自动发现本机 9223 会话
.\.venv\Scripts\python.exe -m apps.cli run <post_id> --platform toutiao --login-hold 0 --wait-timeout 600

# 同时保存到两个平台；小红书目标仍要求草稿先通过 approve
.\.venv\Scripts\python.exe -m apps.cli run <post_id> --platform both --headless --login-hold 0 --wait-timeout 600

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
- 每日新闻只使用北京时间发帖当天和前一天的来源；缺少可解析日期或更旧的候选直接舍弃，数量不足也不会扩大窗口。
- 生成超过 2 条时至少包含 1 条中国大陆新闻；超过 5 条时至少包含 2 条中国大陆新闻。
- 正文使用简体中文，不写“原文标题”段落；每日新闻的来源链接保存在本地元数据，避免将长链接写入草稿正文。
- 写作时严格区分已核事实、来源表述、计划安排和分析判断，并区分发生时间、发布时间与当前状态。

### 草稿完整性保护

- `assets/empty/*` 和 `assets/empty/**` 固定表示“没有本地素材，改用自动生图”。即使该目录中误放了文件，程序也不会把它们作为草稿图片重复上传；请将真实本地图片放在其他明确目录。
- `run` 和 `retry` 默认只上传 `post.json` 中冻结的最终图片清单。VLM 重画前的失败图片即使仍保留在本地资产目录，也不会混入草稿；只有旧帖子没有清单时才兼容扫描目录。显式传入 `--assets-glob` 仍可人工覆盖。
- 文案模型出现 `429` 或限流提示时，程序默认等待 65 秒，最多重试 3 次。可用 `LLM_RATE_LIMIT_RETRY_SECONDS` 和 `LLM_RATE_LIMIT_MAX_RETRIES` 调整。
- 可恢复的 UTF-8/GBK 乱码会在生成和命令入口处修复；无法修复的乱码、生成失败占位正文以及同批标题/正文重复的草稿都会被阻止保存和上传。无效草稿不会占用重复指纹，因而不会误拦截后续有效替代稿。
- 启用统一预检后，上传前还会核验来源日期、简体中文、历史来源/事件重复、图片可解码性和空白图，并使用有免费额度的视觉模型检查图片是否符合标题、正文与评价。
- VLM 返回分数、问题和重画建议。每日新闻图片不一致时，程序会用无文字、无伪造品牌/界面的约束有限重画；达到上限仍不一致则停止上传，不无限消耗额度。
- 保存按钮成功不等于任务完成。程序会重新进入草稿箱并打开目标草稿，回读完整标题、正文和图片数量；任一不一致都会把该条标记为失败。
- `auto` 批量保存成功后会同步写入本地 `xhs_draft` 元数据（草稿标题、保存时间和执行记录 ID），让后续的草稿更新与排查始终指向实际已验证的草稿。
- 故障复盘、处置边界和验证记录仅保留在本地开发文档中。

### 今日头条适配

- 头条号使用与小红书相同的冻结事实、评价和最终图片，不重新抓取或改写事件事实；标题会在不添加新事实的前提下清理并限制为 30 个字符。
- 普通新闻正文会把小红书短内容分段调整为“事件概况、观察与评价、信息时间、资料来源”的文章结构；`每日AI讯息` 直接从冻结条目生成编号式简报，保留发布时间与来源名称。
- 为避免正文出现平台导流和失效长链，AI 简报默认不复制原始 URL 到头条正文；本地帖子元数据继续保留完整证据链。
- 头条自动化会写入标题和正文、插入最终图片、保存草稿，再进入内容管理的草稿列表按标题核验。未通过草稿箱回读时不会报告成功。
- 草稿回读分别报告标题、正文、图片和封面状态。封面 DOM 因懒加载暂不可见时，会再核对头条官方草稿列表返回的 `cover_image`，避免把已保存封面误判为缺失。
- 复制自小红书的内容会取消头条页面默认勾选的“头条首发”，并声明“取材网络”和“引用AI”，避免对跨平台内容作出错误的独家或人工原创声明。
- 当前只保存头条号草稿，不自动正式发布。可以在头条号后台人工预览、修改封面和确认声明后再发布。

### 每日AI讯息

- 官方模型动态优先，AI 搜索/热点补充其次，Hugging Face 等综合模型站作为最后兜底。
- `每日AI讯息` 默认要求至少 6 条可直接访问的官网或官方项目发布链接；聚合页（包括 AI HOT）和社交媒体只能补充剩余条目，不能冒充官网来源。3 天内官网材料不足时会按 7 天、14 天回溯；仍不满足则停止生成并说明不足原因。
- AI HOT 条目会继续解析详情页的原始外链；原链通过厂商域名核验后，正文与图片只展示厂商官网，AI HOT 详情页仅保留在本地证据链中。
- 优先模型发布、版本更新、API、开发者工具、评测、开源项目和基础设施；观点讨论类内容只作补充。
- “模型”按 AI 语义识别；DCF、估值模型、盈利预测等财经语境不会被误判为 AI 模型发布。
- 每一页展示发布时间，正文保存来源链接；图片不放长链接。
- 真实日期由来源发布时间和北京时间窗口决定，模型不得自行改写成“今天”或其他日期。
- 使用 Volcengine 生成结构化简报时会关闭该次 JSON 调用的深度思考模式，并保留 60000 token 上限，避免思考内容耗尽输出导致空 JSON；非结构化文案不受此设置影响。

## 目录结构

```text
apps/                 CLI、GUI 和端到端入口
src/news/             每日新闻候选获取、去重和筛选
src/ai_digest/        每日AI讯息采集、排序、生成和渲染
src/llm/              LLM 调用封装
src/images/           Aliyun、Volcengine、Pexels 和本地图片处理
src/publish/           小红书与头条号草稿保存、回读和平台适配
src/analytics/        已发布数据同步和分析
src/storage/          本地 JSON/CSV/JSONL 存储
src/workflow/         统一预检、免费模型调度、质量门禁和视觉复核
tests/                单元测试和回归测试
```

## 本地数据与密钥安全

下列内容只应保留在本地，默认不会提交：

- `data/`、`logs/`、`output/`：帖子、图片、运行记录、额度快照和同步数据。
- `docs/`、`assets/` 和本地图片：开发计划、实测报告、截图、生成图和素材；这些内容不会提交到仓库。
- `.env`、`.env.*`、`.env.gui`：本地环境变量。
- `.venv/`、`.playwright-browsers/`：本地运行环境和浏览器缓存。
- 浏览器 Profile、登录态、Cookie、证书和私钥文件。
- `AGENT.md`、`CODING_PROGRESS.md`：本地协作记录。

提交前检查：

```powershell
git status --short
git diff --check
git ls-files docs assets
git ls-files | Select-String -Pattern "api-key\.md$|(^|/)\.env($|\.)|^data/|browser|\.(png|jpe?g|webp|gif|bmp|avif)$|\.key$|\.pem$|\.p12$|\.pfx$"
git grep -n -I -E "sk-[A-Za-z0-9]{20,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" -- .
```

发现真实密钥或登录数据时，先移出 Git 跟踪范围；不要通过提交后再删除的方式处理泄漏。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m compileall -q apps src tests
git diff --check
```

显式指定 `tests/` 可以避免 `data/release_check_*` 等本地发布备份中可能存在的旧测试副本被 pytest 重复收集。

网络供应商、控制台登录态和创作平台账号属于外部条件。端到端实测记录只保留在本地；真实密钥、本地数据、图片、开发文档和浏览器登录态不会提交到仓库。
