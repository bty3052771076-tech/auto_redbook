# Auto Redbook Workflow

本项目用于在本地生成小红书图文内容，并通过 Playwright 自动保存为草稿（不发布）。

## 免费运行说明（默认配置即可）
- 文案生成：优先使用阿里云百炼（默认 `qwen3.7-plus`，OpenAI 兼容接口），可切换 ppinfra
- 图片来源：默认使用阿里云百炼文生图（默认 `wan2.7-image`）；也可手动切换 Pexels 图片检索
- 新闻来源：支持 NewsAPI / GNews / 聚合数据 Juhe / 已核验本地候选文件；不再使用 GDELT 回退
- 费用说明：上述能力在**免费额度内可运行**；若超出平台免费额度会产生计费，请自行关注控制台余额/配额

> ⚠️ 费用/额度风险提示：请务必在阿里云百炼控制台确认你的**免费额度**与**到期时间**。超出免费额度后将产生计费，建议在运行前检查余额/配额并设置合理的调用频率。

## 快速使用
### 需要准备什么
- 小红书账号：用于登录小红书创作服务平台。本项目只保存草稿，不绕过扫码、验证码或平台风控。首次使用请用可视浏览器登录一次。
- 阿里云百炼 / DashScope 账号：默认用于 LLM 文案生成和 AI 生图。运行前请确认 API Key、免费额度、到期时间和是否已开通对应模型。
- Python 环境：推荐 Python 3.10+。不要在 C 盘安装项目依赖；虚拟环境、pip 缓存和 Playwright 浏览器建议都放在当前工作区。
- 新闻源账号：推荐至少准备 GNews、NewsAPI 或聚合数据 Juhe 中的一个。没有可用新闻源时，“每日新闻”可能无法获取候选新闻。
- Chrome / 小红书登录态：默认使用本项目工作区内的 `data/browser/chrome-profile`。请用 GUI 顶部“登录/检查Profile”或 `Open-XHS-Creator.cmd` 登录，避免误用系统默认 Chrome 账号。

### 需要编辑或创建什么文件
- `README.md`：只看说明，不需要填写密钥。
- `.env.gui`：可选。通过 GUI “配置”页保存本机配置；该文件已被 `.gitignore` 忽略，不会上传 GitHub。
- `docs/aliyun_image_api-key.md`：可选。由 `docs/aliyun_image_api-key.example.md` 复制而来，填写阿里云生图 Key；真实文件已被忽略。
- `docs/llm_api-key.md`：可选。由 `docs/llm_api-key.example.md` 复制而来，填写 ppinfra/OpenAI-compatible 备用 LLM Key；真实文件已被忽略。
- `docs/news_api-key.md`：可选。由 `docs/news_api-key.example.md` 复制而来，填写 NewsAPI Key；真实文件已被忽略。
- `docs/gnews_api-key.md`：可选。由 `docs/gnews_api-key.example.md` 复制而来，填写 GNews Key；真实文件已被忽略。
- `docs/juhe_api-key.md`：可选。由 `docs/juhe_api-key.example.md` 复制而来，填写聚合数据新闻头条/财经新闻 Key；真实文件已被忽略。
- `assets/pics/`：可选。本地图片素材目录。若使用 `assets/empty/*` 且无本地图片，会触发自动配图。
- `XHS_PUBLISHED_URL`：可选。若小红书后台“已发布/笔记管理”页面路径变化，可在 `.env.gui` 或 PowerShell 环境变量中设置该 URL，供互动数据同步使用。

建议优先使用 PowerShell 环境变量配置密钥，不把真实 Key 写入仓库文件：

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

### 首次初始化
PowerShell 中运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PIP_CACHE_DIR=(Resolve-Path ".").Path + "\.pip-cache"
$env:PLAYWRIGHT_BROWSERS_PATH=(Resolve-Path ".").Path + "\.playwright-browsers"
pip install -r requirements.txt
python -m playwright install chromium
```

### 最短启动方式
启动 GUI：

```powershell
.\AutoRedbookGUI-Launcher.exe
```

命令行生成并保存 1 条每日新闻草稿：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --evaluation-viewpoint "无视角评价" --assets-glob "assets/empty/*" --count 1 --login-hold 600 --wait-timeout 600 --force
```

如果已经在工作区 Chrome profile 登录过小红书，可改用无界面上传，并在终端查看上传进度：

```powershell
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --evaluation-viewpoint "无视角评价" --assets-glob "assets/empty/*" --count 1 --login-hold 0 --wait-timeout 600 --force --headless
```

同步已发布笔记的点赞、评论、收藏到本地表格：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 50 --login-hold 600 --wait-timeout 600
```

如果 profile 已登录，可无界面同步：

```powershell
.\.venv\Scripts\python.exe -m apps.cli update-metrics --limit 50 --headless --login-hold 0 --wait-timeout 600
```

GUI 查看方式：打开 `已发布数据` 页签，点击 `更新已发布数据：点赞 / 评论 / 收藏` 同步平台数据；下方表格会读取 `data/analytics/published_metrics_latest.csv`，点击 `点赞`、`评论`、`收藏`、`浏览` 等列头可切换升序/降序排序。

### 上传安全
- 不要提交真实 API Key、`.env.gui`、浏览器 profile、草稿记录或测试截图。
- `.gitignore` 已忽略 `.env*`、`docs/*api-key.md`、`data/`、`output/`、`.venv/` 和本地 GUI exe。
- `data/posts/` 是本地新闻草稿记录，会保留在本机，不会上传 GitHub。
- `data/analytics/published_metrics_latest.csv` 保存去重后的最新互动数据，适合直接分析；`published_metrics.csv/jsonl` 保留每次同步快照；`data/runs/run_records.csv` 保存每次生成/上传运行记录。它们都在 `data/` 下，仅本地保存。

## 功能一览
- 普通图文：`标题 + 提示词（可选） + 图片（可选）` → 生成草稿并保存到草稿箱
- 特殊标题「每日新闻」：自动抓取新闻 → 生成草稿并保存
- 特殊标题「每日假新闻」：LLM 生成幽默虚构新闻 → 生成草稿并保存
- 批量生成：使用 `--count` 控制单次生成条数（默认 1）
- 图形界面（GUI）：在窗口中选择模型/参数并一键执行常用命令
- 自动配图：当未提供图片时，默认用阿里云百炼生成 1 张相关图片用于上传，也可切换 Pexels 检索下载
- 无界面上传：`run` / `auto` / `retry` / `delete-drafts` 支持 `--headless`，终端会实时显示上传步骤和 `uploaded=x/y` 进度
- 已发布数据同步：`update-metrics` 可抓取已发布稿件的点赞、评论、收藏，并写入 `data/analytics/published_metrics_latest.csv` 与快照文件 `published_metrics.csv/jsonl`；GUI 的 `已发布数据` 页可用表格查看并按点赞、评论、收藏、浏览等列排序
- 运行记录：`create` / `auto` 会记录本次生成条数、上传条数、失败条数、LLM/VLM/新闻源等信息到 `data/runs/run_records.csv/jsonl`
- 部分成功保护：批量每日新闻如果中途遇到额度不足、候选不足或生图失败，已经生成的草稿不会丢弃，`auto` 会继续上传已生成部分并汇报 generated/uploaded/failed
- 删除草稿：清理草稿箱（图文/视频/长文），支持预览/限量/全量删除
- 落盘与可追溯：`data/posts/<post_id>/` 保存 post / revision / execution / evidence

## 快速开始（推荐顺序）
```powershell
# 0) 创建并激活虚拟环境（首次）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 1) 安装依赖与浏览器（首次）
$env:PIP_CACHE_DIR=(Resolve-Path ".").Path + "\.pip-cache"
$env:PLAYWRIGHT_BROWSERS_PATH=(Resolve-Path ".").Path + "\.playwright-browsers"
pip install -r requirements.txt
python -m playwright install chromium

# 2) 配置密钥（推荐用环境变量）
#   - ALIYUN_LLM_API_KEY：生成文案（推荐，Aliyun qwen3.7-plus）
#   - LLM_API_KEY：生成文案（可选：作为阿里云无额度时的备用）
#   - ALIYUN_IMAGE_API_KEY：生图（可与 LLM 共用同一把 DashScope Key）
#   - NEWS_API_KEY / GNEWS_API_KEY / JUHE_NEWS_APPKEY：每日新闻（至少配置一个在线新闻源，或使用 NEWS_PROVIDER=file）
#   - PEXELS_API_KEY：Pexels 备用配图（可选；默认配图走阿里云生图）
# 例如（PowerShell）：
#   $env:ALIYUN_LLM_API_KEY="..."
#   $env:ALIYUN_IMAGE_API_KEY="..."
#
# 3) 一键：生成 -> 校验/审批 -> 保存草稿（首次建议给更长登录时间）
.\.venv\Scripts\python -m apps.cli auto --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" --login-hold 600
```

## 图形界面（GUI）
适合不想手工拼参数/环境变量时使用（本地配置可保存到 `.env.gui`，已被 `.gitignore` 忽略）：  
```powershell
.\.venv\Scripts\python -m apps.gui
```
如果只想双击启动当前设计版 GUI，使用轻量启动器：
```powershell
.\AutoRedbookGUI-Launcher.exe
```
也可以使用脚本入口：
```powershell
.\Start-GUI.cmd
```
GUI 内置常用工作流页签：`自动发帖` / `仅生成` / `草稿处理` / `已发布数据` / `删除草稿` / `配置`。自动发帖页可直接选择 LLM 供应商（阿里云 / ppinfra / auto）、LLM 模型、图片来源（`local` 本地 assets / `aliyun` AI 生图 / `pexels` 搜图）和阿里云生图模型；`草稿处理` 页会按“标题 + 状态 + post_id”列出最近帖子，并在独立时间框显示北京时间，便于确认每个帖子的标题后再审核或上传；`已发布数据` 页可一键同步点赞、评论、收藏到本地表格，并直接查看本地最新数据，点击列头按点赞、评论、收藏、浏览、分享或同步时间排序。

图片来源说明：选择 `local` 时使用本地 `assets glob`；选择 `aliyun` 或 `pexels` 时 GUI 会自动使用 `assets/empty/*` 触发自动配图，避免本地旧图片覆盖你选择的图片来源。

`自动发帖`、`草稿处理` 和 `删除草稿` 页提供“无界面上传/运行”选项。首次登录或遇到验证码时不要勾选；确认 `data/browser/chrome-profile` 已登录后再勾选，上传进度会显示在 GUI 日志区。

长任务运行时，GUI 日志区会定期输出“仍在运行”心跳，并在右侧显示 `空闲` / `运行中` / `正在停止` 状态。如果心跳持续很久，通常是在等待新闻 API、LLM、VLM 生图或小红书页面响应，不等同于窗口冻结。

更多说明见：`docs/模型与GUI供应商配置.md`。

已发布互动数据同步、运行记录和部分成功保护说明见：`docs/发布数据同步与运行记录-2026-06-27.md`。

### 生成快速启动 exe（可选）
```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_gui_exe.ps1
```
生成：`AutoRedbookGUI-Launcher.exe`（放在仓库根目录，双击后调用 `.\.venv\Scripts\pythonw.exe -m apps.gui`）。

旧的 `AutoRedbookGUI.exe` 是历史打包产物，不再推荐使用。

为避免空终端窗口，当前启动器只使用 `pythonw.exe`；如果 `.venv\Scripts\pythonw.exe` 不存在，会弹窗提示修复虚拟环境，不再回退到会显示控制台的 `python.exe`。`Start-GUI.cmd` 也会优先隐藏启动 `pythonw.exe`。

## 草稿与浏览器 Profile
- 草稿箱数据保存在浏览器本地 profile 中，不同 profile 互不可见。
- 默认使用：`data/browser/chrome-profile`（复用 Chrome 渠道）。
- GUI 顶部的“打开小红书创作平台”、`登录/检查Profile` 和 `Open-XHS-Creator.cmd` 都会使用这个 profile，而不是系统默认浏览器 profile。
- 若需自定义 profile，设置：
  - `XHS_BROWSER_CHANNEL=chrome`
  - `XHS_CHROME_PATH=<chrome.exe 路径>`（可选；找不到 Chrome 时使用）
  - `XHS_CHROME_USER_DATA_DIR=<profile 目录>`
  - `XHS_CHROME_PROFILE=Default`（或 `Profile 1` 等）
- 无界面上传可通过 CLI `--headless` 或环境变量 `XHS_HEADLESS=1` 开启；必须复用已登录 profile，首次登录、扫码和验证码仍需使用可视浏览器或 GUI 的 `登录/检查Profile`。

查看草稿（默认 profile）：
```powershell
$chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
$profile = (Resolve-Path "data/browser/chrome-profile").Path
& $chrome --user-data-dir="$profile" --profile-directory="Default"
```

## 环境准备
```powershell
# 0) 创建虚拟环境（首次）
python -m venv .venv

# 1) 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 2) 安装依赖
$env:PIP_CACHE_DIR=(Resolve-Path ".").Path + "\.pip-cache"
pip install -r requirements.txt

# 3) 安装 Playwright 浏览器
$env:PLAYWRIGHT_BROWSERS_PATH=(Resolve-Path ".").Path + "\.playwright-browsers"
python -m playwright install chromium
```

## Secrets / API Keys（不要提交到仓库）
- 本仓库已在 `.gitignore` 中忽略：`.env*`、`docs/*api-key.md` 等敏感文件。
- 推荐使用环境变量（更安全），或仅在本机创建 `docs/*api-key.md`（不要提交）。

LLM（生成文案）：
- 主用（阿里云百炼 / DashScope，默认 `qwen3.7-plus`）：
  - 环境变量：`ALIYUN_LLM_API_KEY`（或 `ALIYUN_IMAGE_API_KEY` / `DASHSCOPE_API_KEY`）
  - 可选：`ALIYUN_LLM_MODELS`（文本模型候选列表，逗号/空格分隔，按顺序尝试；优先于 `ALIYUN_LLM_MODEL`）
  - 可选：`ALIYUN_LLM_MODEL`（单个文本模型，默认 `qwen3.7-plus`；仅在未设置 `ALIYUN_LLM_MODELS` 时使用）
  - 可选：`ALIYUN_LLM_BASE_URL`（默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`）
- 备用（ppinfra / OpenAI 兼容提供商）：
  - 环境变量：`LLM_API_KEY`，可选 `LLM_MODEL` / `LLM_BASE_URL`
  - 或本机文件：复制 `docs/llm_api-key.example.md` 为 `docs/llm_api-key.md` 并填写
- 可选：`LLM_PROVIDER=auto|aliyun|ppinfra`。`auto` 表示阿里云优先；当出现额度/限流/模型不可用等错误时自动回退到 ppinfra。
- 阿里云免费模型完整列表见：`docs/模型与GUI供应商配置.md`

新闻源（“每日新闻”）：
- 环境变量：`NEWS_API_KEY`（或 `NEWSAPI_API_KEY`），可选 `NEWS_BASE_URL`
- 或本机文件：复制 `docs/news_api-key.example.md` 为 `docs/news_api-key.md` 并填写
- GNews 备用源：环境变量 `GNEWS_API_KEY`（或 `GNEWS_TOKEN`），可选 `GNEWS_LANG` / `GNEWS_COUNTRY` / `GNEWS_MAX` / `GNEWS_BASE_URL`
- 或本机文件：复制 `docs/gnews_api-key.example.md` 为 `docs/gnews_api-key.md` 并填写
- 聚合数据 Juhe 国内源：环境变量 `JUHE_NEWS_APPKEY`（新闻头条）和/或 `JUHE_FINANCE_NEWS_APPKEY`（财经新闻），可选 `JUHE_NEWS_TYPE` / `JUHE_NEWS_FETCH_DETAIL` / `JUHE_NEWS_DETAIL_LIMIT`
- 或本机文件：复制 `docs/juhe_api-key.example.md` 为 `docs/juhe_api-key.md` 并填写；该文件已被 `.gitignore` 忽略，不能提交
- 已核验候选文件：`NEWS_PROVIDER=file` + `NEWS_CANDIDATES_FILE=data/news/xxx.json`，适合在线 API 临时不可用、但仍需要使用真实来源新闻完成自动生成与草稿保存时使用
- 注意：`GDELT` 已从自动新闻源中移除；`NEWS_PROVIDER=gdelt` 会直接报不支持，避免仅凭低质量摘录生成草稿
- 中国/海外新闻比例：默认偏向中国新闻，约 6:4（可用 `NEWS_CHINA_RATIO=0.6` 调整；仅影响“每日新闻”候选排序/挑选）

Pexels（自动配图：当未提供图片素材时）：
- 环境变量：`PEXELS_API_KEY`，可选 `PEXELS_BASE_URL` / `AUTO_IMAGE_COUNT` / `IMAGE_MIN_SCORE`；`AUTO_IMAGE=0` 可关闭自动配图
- 或本机文件：复制 `docs/pexels_api-key.example.md` 为 `docs/pexels_api-key.md` 并填写

阿里云百炼 / DashScope（API 生图：当未提供图片素材时）：
- 环境变量：`ALIYUN_IMAGE_API_KEY`（或 `DASHSCOPE_API_KEY`），可选 `ALIYUN_IMAGE_BASE_URL` / `ALIYUN_IMAGE_MODELS` / `ALIYUN_IMAGE_MODEL` / `ALIYUN_IMAGE_SIZE`
- 或本机文件：复制 `docs/aliyun_image_api-key.example.md` 为 `docs/aliyun_image_api-key.md` 并填写

如曾泄露密钥：请立即在对应平台轮换/作废旧 key。

## 使用顺序（推荐）
推荐直接使用 `auto` 一键完成：
1) 准备图片：放到 `assets/pics/*`；或配置阿里云生图 Key 让系统在“无图”时自动生成配图
2) 首次登录：运行时把 `--login-hold` 设大一些（例如 600 秒）用于扫码登录
3) 执行一键保存草稿：

```powershell
.\.venv\Scripts\python -m apps.cli auto --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" --login-hold 600
```

## 使用顺序（手动分步）
需要更可控/便于排查时按以下顺序：
```powershell
# 1) 生成内容并落盘（捕获 post_id）
$out = .\.venv\Scripts\python -m apps.cli create --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" 2>&1
$out
$post_id = ($out | Select-String -Pattern "post_id=([0-9a-f]{32})" | Select-Object -First 1).Matches[0].Groups[1].Value

# 2) 校验（可选）
.\.venv\Scripts\python -m apps.cli validate $post_id

# 3) 审批（标记为 approved）
.\.venv\Scripts\python -m apps.cli approve $post_id

# 4) 保存草稿（首次建议加长 login_hold）
.\.venv\Scripts\python -m apps.cli run $post_id --login-hold 600

# 5) 失败后重试
.\.venv\Scripts\python -m apps.cli retry $post_id --force
```

## CLI 命令一览
- `create`：生成草稿并落盘（输出 `post_id`）
- `list`：列出现有 post
- `show <post_id>`：打印 `post.json` 详情
- `validate <post_id>`：校验（不改状态）
- `approve <post_id>`：校验并标记为 `approved`
- `run <post_id>`：用 Playwright 上传图片/填写标题正文/保存草稿
- `auto`：一键完成 `create -> approve -> run`
- `update-metrics`：同步已发布稿件点赞、评论、收藏到本地表格
- `retry <post_id>`：对失败的 run 进行重试
- `delete-drafts`：删除草稿箱草稿（默认图文）

## 功能示例
### 1) 标题 + 简略提示词 + 图片齐全 → LLM 文案 → 保存草稿
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
.\.venv\Scripts\python -m apps.cli auto --title "冬日穿搭" --prompt "通勤简约风，给我3套搭配思路" --assets-glob "assets/pics/*" --login-hold 600
```

### 2) 标题为“每日新闻” → 新闻 API 获取当日新闻并按提示词挑选 → 保存草稿
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
$env:NEWS_API_KEY="YOUR_NEWS_API_KEY"
$env:NEWS_PROVIDER="newsapi"

# 有提示词：挑选最匹配 1 条新闻
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --prompt "美国时政" --assets-glob "assets/pics/*" --login-hold 600

# 无提示词：默认生成 1 条，可用 --count 调整
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --assets-glob "assets/pics/*" --login-hold 600
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --assets-glob "assets/pics/*" --count 3 --login-hold 600

# 外部新闻 API 临时不可用时：使用已核验 JSON 候选文件
$env:NEWS_PROVIDER="file"
$env:NEWS_CANDIDATES_FILE="data/news/manual_candidates_20260619.json"
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --prompt "科技、社会或国际新闻" --assets-glob "assets/empty/*" --count 5 --login-hold 0 --wait-timeout 300 --force
```

### 2.1) 使用 GNews 作为新闻源
```powershell
$env:GNEWS_API_KEY="YOUR_GNEWS_API_KEY"
$env:NEWS_PROVIDER="gnews"
$env:GNEWS_LANG="en"
$env:GNEWS_COUNTRY="us"

.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*" --count 2 --login-hold 600 --wait-timeout 600
```

### 2.2) 使用聚合数据 Juhe 作为新闻源
```powershell
$env:NEWS_PROVIDER="juhe"
$env:JUHE_NEWS_APPKEY="YOUR_JUHE_NEWS_APPKEY"
$env:JUHE_FINANCE_NEWS_APPKEY="YOUR_JUHE_FINANCE_NEWS_APPKEY"

# 科技/社会/国际等主题会走“新闻头条”；财经、business、economy 等主题优先走“财经新闻”
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*" --count 2 --login-hold 600 --wait-timeout 600
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --prompt "财经" --assets-glob "assets/empty/*" --count 2 --login-hold 600 --wait-timeout 600
```

### 3) 无图片上传 → 阿里云生图（默认）→ 保存草稿
前提：已配置 `ALIYUN_IMAGE_API_KEY` 或 `DASHSCOPE_API_KEY`（或本机 `docs/aliyun_image_api-key.md`）。
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
$env:ALIYUN_IMAGE_API_KEY="YOUR_DASHSCOPE_KEY"
$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_MODEL="wan2.7-image"
.\.venv\Scripts\python -m apps.cli auto --title "上海周末咖啡馆推荐" --prompt "安静、适合学习办公" --assets-glob "assets/empty/*" --login-hold 600
```

### 4) 标题为“每日假新闻” → LLM 生成幽默虚构新闻 → 保存草稿
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
.\.venv\Scripts\python -m apps.cli auto --title "每日假新闻" --prompt "火星快递、外卖延迟" --assets-glob "assets/pics/*" --login-hold 600
```

### 5) 删除草稿（预览/删除）
```powershell
# 预览将删除的草稿（不会实际删除）
.\.venv\Scripts\python -m apps.cli delete-drafts --dry-run --login-hold 60

# 删除图文草稿（最多 5 条，跳过确认）
.\.venv\Scripts\python -m apps.cli delete-drafts --limit 5 --yes --login-hold 60
```

## auto 参数说明
- `--title`：标题（必填）
- `--prompt`：提示词（可选）
- `--evaluation-viewpoint`：每日新闻评价视角，默认 `无视角评价`；默认不预设国家、行业、投资者或平台立场
- `--count`：生成草稿数量（默认 1）
- `--assets-glob`：素材路径（glob），默认 `assets/pics/*`
- `--no-copy`：不复制素材到 `data/posts/<id>/assets`（默认会复制，便于隔离）
- `--login-hold`：登录完成检测的最长等待秒数；若已登录并进入编辑器会立刻继续，不再固定等待整段时间，默认 0
- `--wait-timeout`：等待发布页秒数，默认 300
- `--dry-run`：只抓取证据，不上传/不保存
- `--force`：忽略校验失败继续执行（仅排查用）

## create/run 常用参数
- `create`：`--assets-glob` / `--no-copy` / `--count` / `--evaluation-viewpoint`（仅每日新闻使用）
- `run`：`--assets-glob` / `--login-hold` / `--wait-timeout` / `--dry-run` / `--force`

## 每日新闻（特殊标题）
- 当 `--title "每日新闻"`：会先拉取新闻候选，再生成草稿。
  - 生成条数由 `--count` 控制（默认 1）
  - 提供 `--prompt`：按提示词相关性排序后取前 N 条
  - 不提供 `--prompt`：从默认通用主题池中随机排序并抓取候选，再取前 N 条
  - 可用 `--evaluation-viewpoint` 指定 `评价` 部分的分析视角，默认 `无视角评价`；无视角评价只基于已给事实和原文摘录客观分析，信息不足时评价可为空
  - 正文最终保存为可直接发布的中文文本，按 `原文标题` / `内容` / `评价` / `日期` / `来源` 五段渲染，五段之间保留空行，不会把 JSON 原文写入正文
  - `评价` 可为空；有可核验事实时才输出具体客观点，信息不足时不硬凑点评
  - 正文不输出 URL；原始链接只保存在本地 metadata
  - 标题会被 LLM 和兜底逻辑规范为 12-18 字中文总结标题，理想约 15 字，不再自动添加“每日新闻｜”前缀，不得直接照搬 `原文标题`，并会清理日文假名
  - `内容` 字段会压缩到 150 字以内，并清理浏览器升级提示、栏目导航、素材地址、站内推荐标题和空泛模板句
  - 最终成稿前会兜底过滤与新闻主题无关的评价模板，例如文化新闻误写成 AI/版权评价、外交新闻误写成经贸供应链评价
  - 默认会尝试抓取原新闻正文后再交给 LLM 总结；若原文仍不足，则要求保守表达、不得推测

可选配置（环境变量）：
- `NEWS_PROVIDER`：`auto` / `newsapi` / `gnews` / `juhe` / `file`（默认自动；顺序为已配置的 NewsAPI -> 已配置的 GNews -> 已配置的 Juhe，已设置 `NEWS_CANDIDATES_FILE` 时优先 file；没有可用 key 时会明确报错）
- `GNEWS_API_KEY` / `GNEWS_TOKEN`：GNews key。推荐使用环境变量；也可创建本机私密文件 `docs/gnews_api-key.md`，该文件已被 `.gitignore` 忽略
- `GNEWS_LANG`：GNews 语言过滤，例如 `en` / `zh`
- `GNEWS_COUNTRY`：GNews 国家过滤，例如 `us` / `cn`
- `GNEWS_MAX`：GNews 单次请求返回条数；免费额度建议保持默认 10
- `GNEWS_BASE_URL`：默认 `https://gnews.io/api/v4`
- `JUHE_NEWS_APPKEY` / `JUHE_NEWS_KEY` / `JUHE_TOUTIAO_APPKEY`：聚合数据新闻头条 key，用于国内、国际、科技、社会等分类新闻
- `JUHE_FINANCE_NEWS_APPKEY` / `JUHE_FINANCE_APPKEY` / `JUHE_CAIJING_APPKEY`：聚合数据财经新闻 key；当 query 包含 `财经` / `business` / `economy` / `finance` 等词时优先使用
- `JUHE_NEWS_TYPE`：强制指定新闻头条分类，例如 `top` / `shehui` / `guonei` / `guoji` / `keji` / `caijing`
- `JUHE_NEWS_FETCH_DETAIL`：默认 `1`，会用新闻头条的 `uniquekey` 尝试拉取详情正文；设为 `0` 可关闭
- `JUHE_NEWS_DETAIL_LIMIT`：默认最多对前 10 条候选拉详情，避免一次请求过多消耗额度
- `NEWS_TZ`：默认 `Asia/Shanghai`
- `NEWS_QUERY_DEFAULT`：自定义默认 query；可写单个 query，也可用逗号/分号分隔多个 query。未设置时使用通用主题池（technology/world/science/business/health/climate/society/international），不再默认固定为 `china`
- `NEWS_SOURCE_LOOKUP`：默认 `1`，会尝试抓取原新闻正文辅助总结；设为 `0` 可关闭
- `NEWS_SOURCE_LOOKUP_TIMEOUT_S`：原新闻摘录抓取超时，默认 `8`
- `NEWS_SOURCE_LOOKUP_MAX_CHARS`：原新闻正文保留字符数，默认 `5000`
- `NEWS_SOURCE_CONTEXT_MIN_CHARS`：判断候选内容是否不足的阈值，默认 `120`
- `NEWS_HISTORY_DEDUPE`：默认 `1`，会跳过本地历史草稿中已经使用过的新闻 URL；设为 `0` 可关闭

## 每日假新闻（特殊标题）
- 当 `--title "每日假新闻"`：使用 LLM 生成一条幽默、明显虚构的娱乐新闻，并保存草稿。
- 建议提供 `--prompt` 作为主题提示；正文会强制包含“本文纯属虚构，仅供娱乐。”。

## 提示词（Prompt）修改入口（代码位置）
为了方便你快速改“生成文案/每日新闻/每日假新闻/生图”的提示词，本项目所有核心提示词都集中在以下位置：

- 普通图文（标题/正文/topics 的 LLM 结构化输出）：`src/llm/generate.py` → `generate_draft()` → `ChatPromptTemplate.from_messages(...)`
  - `system`：整体写作风格、字数要求、JSON 输出要求等
  - `user`：把 `prompt_hint/title_hint/assets` 注入模型
  - 默认 `max_tokens=25565`；实际可用输出长度仍受供应商、模型上下文窗口和账号额度限制
- 每日新闻（给 LLM 的“新闻写作提示词”）：`src/workflow/create_post.py` → `_daily_news_prompt(...)`
  - 同文件：`_daily_news_offline_body(...)` / `_ensure_daily_news_sections(...)` / `_daily_news_body_to_fields(...)` / `_render_daily_news_body_fields(...)`（离线兜底、旧结构兼容、五字段提取与最终正文渲染）
  - `body` 最终固定渲染为 5 段可读正文；`评价` 可为空，避免空泛模板句；原始 URL 只进入本地 metadata
- 每日假新闻（给 LLM 的“虚构新闻提示词”）：`src/workflow/create_post.py` → `_fake_news_prompt(...)`
  - 同文件：`_fake_news_offline_body(...)`（离线兜底）
- 阿里云百炼文生图（把主题/要点拼成生图提示词）：`src/images/auto_image.py` → `_build_aliyun_image_prompt(...)`
  - 同文件：`build_image_query(...)`（用于检索/补图时的 query 生成；影响“相关性”）
  - 可选负面提示词（negative prompt）与自动扩写：`src/images/aliyun_images.py`（读取环境变量 `ALIYUN_IMAGE_NEGATIVE_PROMPT` / `ALIYUN_IMAGE_PROMPT_EXTEND`）

## 自动配图（无图片时）
- 当 `--assets-glob` 未命中任何图片：会自动生成/下载图片到 `data/posts/<post_id>/assets/`，然后继续上传并保存草稿。
- 通过 `IMAGE_PROVIDER` 选择来源：
  - `aliyun`（默认）：阿里云百炼（DashScope）API 生图并落盘（支持 Qwen-Image / Z-Image / 通义万相 wan2.x/wanx 系列）
  - `pexels`：图片检索下载（需要 `PEXELS_API_KEY`）
- 调整张数：`AUTO_IMAGE_COUNT=3`（上限 18；`pexels` 默认 3，`aliyun` 默认 1）。
- 提高相关性：`IMAGE_MIN_SCORE=0.12`（分数越高越严格，图片数量可能减少）。
- 关闭自动配图：`AUTO_IMAGE=0`（注意：图文 post 仍需要至少 1 张图片，否则校验会失败）。

### 阿里云百炼 / DashScope（API 生图，推荐）配置
前提：你已在本机准备好阿里云百炼 API Key（本仓库不会提交密钥）。

配置方式（二选一）：
- 推荐：环境变量 `ALIYUN_IMAGE_API_KEY`
- 或本机文件：复制 `docs/aliyun_image_api-key.example.md` 为 `docs/aliyun_image_api-key.md` 并填写（已被 `.gitignore` 忽略）

支持模型（文生图，模型名以百炼控制台为准，均使用同一把 API Key）：
- 通义万相 2.7：`wan2.7-image` / `wan2.7-image-pro`（GUI 内置，默认 `wan2.7-image`）
- Qwen Image：`qwen-image-2.0-pro-2026-04-22`（GUI 内置，可手动选择测试）
- 兼容旧模型：`qwen-image-plus-2026-01-09` / `qwen-image-max` / `qwen-image` / `z-image-turbo` / `wan2.6-t2i` / `wan2.6-image` / `wan2.5-t2i-preview` / `wanx2.1-t2i-turbo` 等
- 说明：本流程仅使用“文生图”模型；`i2v`/`t2v`/`edit`/`mt-image` 会被自动跳过

常用可选参数（环境变量）：
- `ALIYUN_IMAGE_MODELS`：生图模型候选列表（逗号/空格分隔，按顺序尝试；优先于 `ALIYUN_IMAGE_MODEL`）
- `ALIYUN_IMAGE_MODEL`：生图模型（默认 `wan2.7-image`；仅在未设置 `ALIYUN_IMAGE_MODELS` 时使用）
- `ALIYUN_IMAGE_SIZE`：尺寸（默认 `1104*1472`，3:4 竖图）
- `ALIYUN_IMAGE_TIMEOUT_S`：单次生图请求超时（默认 `180`）
- `ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S`：下载生成图片超时（默认 `60`）
- `ALIYUN_IMAGE_MAX_ATTEMPTS`：单条新闻图片失败最大重试次数（默认 `3`；超限会放弃该条图片）
- `ALIYUN_IMAGE_RETRY_SLEEP_S`：两次重试间隔秒数（默认 `2`）
- `ALIYUN_IMAGE_CALL_MODE`：`auto` / `sync` / `async` / `text2image`（默认 `auto`；wan2.5/wanx 走异步，其它优先同步，失败自动降级）
- `ALIYUN_IMAGE_NEGATIVE_PROMPT`：负面提示词（用于降低“文字/水印/logo/海报排版”等不可用输出；未设置时不会发送）

注意：文生图 API 返回的是图片 URL（通常 24 小时有效），程序会自动下载保存为本地 PNG/JPG 以便上传。

## 相关改进（已落地）
- 阿里云 LLM 优先 + 自动回退：额度不足/限流/模型不可用时自动切换到备用提供商
- 阿里云 LLM 模型列表：支持 `ALIYUN_LLM_MODELS` 按顺序尝试与回退
- 阿里云生图模型列表：支持 `ALIYUN_IMAGE_MODELS` 按顺序尝试与回退
- 生图事件摘要：LLM 输出 `image_event`（约 30 字）用于降低“新闻海报感/文字”概率
- 生图提示词收敛：仅用事件描述生成插画，避免“报道/海报/采访”等语义
- 在线新闻源：支持 `NEWS_PROVIDER=newsapi` / `gnews` / `juhe` / `file`，自动模式只尝试已配置 key 的来源，不再回退到 GDELT
- 每日新闻历史 URL 查重：新候选若与 `data/posts/*/post.json` 中已用新闻链接重复，会自动跳过并选择其他新闻
- 终端阶段化报错：失败时会输出 `stage=获取新闻` / `stage=LLM` / `stage=VLM生图` / `stage=上传`，方便快速定位链路断点
- 元数据完整落盘：每条 post 保存 news/image/attempt 等字段，便于追踪与复盘
- 每日新闻要点摘要：正文首行输出 20-40 字关键摘要，突出新闻要点
- 小红书登录态检测：`--login-hold` 现在只在未登录/页面未就绪时等待，已登录会立即进入上传链路

## 一键快速使用（免费额度版本）
```powershell
# 仅需配置阿里云 Key（用于 LLM + 生图）
$env:ALIYUN_LLM_API_KEY="YOUR_DASHSCOPE_KEY"
# 可选：按顺序尝试多个文本模型（优先于 ALIYUN_LLM_MODEL）
$env:ALIYUN_LLM_MODELS="qwen3.7-plus,deepseek-v4-flash,qwen3.6-flash"
$env:ALIYUN_IMAGE_API_KEY="YOUR_DASHSCOPE_KEY"
$env:NEWS_PROVIDER="gnews"
$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_MODELS="wan2.7-image,wan2.7-image-pro,qwen-image-2.0-pro-2026-04-22"

.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 10 --assets-glob "empty/pics/*" --login-hold 600 --wait-timeout 600
```


**每日新闻一行版（无本地图片 → 阿里云生图 → 保存草稿）**
```powershell
$env:IMAGE_PROVIDER="aliyun"; $env:ALIYUN_IMAGE_MODELS="wan2.7-image,wan2.7-image-pro,qwen-image-2.0-pro-2026-04-22"; $env:ALIYUN_IMAGE_SIZE="1104*1472"; $env:ALIYUN_IMAGE_TIMEOUT_S="180"; $env:ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S="60"; $env:ALIYUN_IMAGE_MAX_ATTEMPTS="3"; .\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 3 --assets-glob "empty/pics/*" --login-hold 600 --wait-timeout 600
```

**每日假新闻一行版（无本地图片 → 阿里云生图 → 保存草稿）**
```powershell
$env:IMAGE_PROVIDER="aliyun"; $env:ALIYUN_IMAGE_MODELS="wan2.7-image,wan2.7-image-pro,qwen-image-2.0-pro-2026-04-22"; $env:ALIYUN_IMAGE_SIZE="1104*1472"; $env:ALIYUN_IMAGE_TIMEOUT_S="180"; $env:ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S="60"; $env:ALIYUN_IMAGE_MAX_ATTEMPTS="3"; .\.venv\Scripts\python -m apps.cli auto --title "每日假新闻" --prompt "火星快递导致地球外卖迟到" --count 1 --assets-glob "empty/pics/*" --login-hold 600 --wait-timeout 600
```

## 删除草稿（危险操作）
说明：删除操作发生在当前浏览器 profile 的草稿箱内；默认仅处理图文草稿，可用 `--all` 覆盖三类草稿。
```powershell
# 预览将删除的草稿（不会实际删除）
.\.venv\Scripts\python -m apps.cli delete-drafts --dry-run

# 删除图文草稿（最多 10 条），需要确认
.\.venv\Scripts\python -m apps.cli delete-drafts --limit 10

# 删除全部类型草稿（跳过确认）
.\.venv\Scripts\python -m apps.cli delete-drafts --all --yes

# 在自定义草稿位置删除（指定草稿页面 URL）
.\.venv\Scripts\python -m apps.cli delete-drafts --draft-location url --draft-url "https://creator.xiaohongshu.com/..." --limit 5 --yes
```

## 输出位置（落盘）
- `data/posts/<post_id>/post.json`：草稿内容与元数据（含 `platform.news` / `platform.image` / `platform.images`）
- `data/posts/<post_id>/revisions/*.json`：每次生成的 revision
- `data/posts/<post_id>/executions/*.json`：每次保存草稿 attempt 的执行记录
- `data/posts/<post_id>/evidence/<execution_id>/`：截图/HTML 等证据文件

## 调试（可选）
仅用于打开发布页/保持登录（不上传/不保存）：
```powershell
$out = .\.venv\Scripts\python -m apps.cli create --title "登录测试" --prompt "" --assets-glob "assets/pics/*" 2>&1
$post_id = ($out | Select-String -Pattern "post_id=([0-9a-f]{32})" | Select-Object -First 1).Matches[0].Groups[1].Value
.\.venv\Scripts\python -m apps.cli run $post_id --login-hold 600 --dry-run --force
```

E2E 测试（需要已配置阿里云百炼 key；可选 `--cdp` 复用你已打开的 Chrome）：
```powershell
# 全流程：每日新闻 -> 阿里云生图 -> 小红书保存草稿（会自动读取 post.json 校验素材落盘）
.\.venv\Scripts\python -m apps.e2e_test_auto_full --image-provider aliyun --title "每日新闻" --prompt "美国时政" --count 1 --assets-glob "empty/pics/*"
```

## 常见问题
- PowerShell 弹出 `Invoke-WebRequest` 安全提醒：关闭旧 GUI 窗口后重新运行 `.\Start-GUI.cmd`。当前启动脚本已在 PowerShell 5.1 下启用 `UseBasicParsing`，如果仍弹出，通常是外部脚本或旧进程触发。
- GUI 看起来卡住：新版 GUI 会每 20 秒输出一次“仍在运行”心跳，并显示当前状态；若持续很久没有步骤输出，可点击“停止当前任务”后用同一条 CLI 命令复现。
- 草稿箱为空：确认打开的是保存草稿时用的同一个 profile（不同 profile 草稿互不可见）。
- 没看到“图文笔记”：只运行了 `create` 不会出现在网页草稿箱；需要 `auto` 或 `approve + run`。
- Playwright 启动失败：关闭所有 Chrome 窗口，避免 profile 被占用。
- 看到 “offline fallback”：说明 LLM 调用失败，请检查 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 是否可用。
- 阿里云生图报错 `AllocationQuota.FreeTierOnly`：说明免费额度已耗尽；请改用本地图片/PEXELS，或在百炼控制台开通计费/提升配额后重试。

## 相关文档（docs）
- `docs/GUI启动与运行稳定性修复-2026-06-22.md`
- `docs/GUI运行流畅度与心跳修复-2026-06-23.md`
- `docs/每日新闻图文不符修复-2026-06-23.md`
- `docs/每日新闻评价半句截断修复-2026-06-23.md`
- `docs/每日新闻原文标题泛化修复-2026-06-23.md`
- `docs/LLM输出token上限调整-2026-06-23.md`
- `docs/每日新闻评价视角参数-2026-06-23.md`
- `docs/每日新闻英文泄漏闸门与两条草稿实测-2026-06-22.md`
- `docs/GUI每日新闻数量不足修复-2026-06-22.md`
- `docs/每日新闻三条草稿最终实测-2026-06-22.md`
- `docs/使用说明-自动新闻生成与草稿发布.md`
- `docs/聚合数据新闻源接入-2026-06-21.md`
- `docs/每日新闻质量闸门与GDELT移除-2026-06-21.md`
- `docs/新闻质量闸门与终端GUI实测-2026-06-20.md`
- `docs/每日新闻正文渲染修复-2026-06-21.md`
- `docs/每日新闻正文JSON结构稳定化-2026-06-20.md`
- `docs/每日新闻点评与正文通顺优化-2026-06-20.md`
- `docs/每日新闻兜底正文与两条草稿实测-2026-06-20.md`
- `docs/每日新闻历史URL查重-2026-06-20.md`
- `docs/工程性全面检测与每日新闻AI配图实测-2026-06-20.md`
- `docs/GUI删除草稿total0诊断-2026-06-21.md`
- `docs/GUI删除草稿验证与提示优化-2026-06-20.md`
- `docs/小红书登录态检测与每日新闻链路实测-2026-06-20.md`
- `docs/新闻中文化与GUI草稿状态修复-2026-06-19.md`
- `docs/模型与GUI供应商配置.md`
- `docs/工作流新闻任务书.md`
- `docs/图片查找功能.md`
- `docs/增加图片api后的错误修正任务书.md`
- `docs/新闻要点摘要任务书.md`
- `docs/新闻时效性去重与内容规范任务书.md`
- `docs/中国海外新闻比例任务书.md`
- `docs/图形界面任务书.md`
- `docs/图形界面工作流增强任务书.md`
