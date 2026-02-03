# Auto Redbook Workflow

本项目用于在本地生成小红书图文内容，并通过 Playwright 自动保存为草稿（不发布）。

## 免费运行说明（默认配置即可）
- 文案生成：优先使用阿里云百炼（DeepSeek-V3.2，OpenAI 兼容接口）
- 图片生成：使用阿里云百炼文生图（Qwen-Image / 通义万相 / Z-Image）
- 新闻来源：默认可使用 GDELT（无需 key 的免费新闻源）
- 费用说明：上述能力在**免费额度内可运行**；若超出平台免费额度会产生计费，请自行关注控制台余额/配额

> ⚠️ 费用/额度风险提示：请务必在阿里云百炼控制台确认你的**免费额度**与**到期时间**。超出免费额度后将产生计费，建议在运行前检查余额/配额并设置合理的调用频率。

## 功能一览
- 普通图文：`标题 + 提示词（可选） + 图片（可选）` → 生成草稿并保存到草稿箱
- 特殊标题「每日新闻」：自动抓取新闻 → 生成草稿并保存
- 特殊标题「每日假新闻」：LLM 生成幽默虚构新闻 → 生成草稿并保存
- 批量生成：使用 `--count` 控制单次生成条数（默认 1）
- 自动配图：当未提供图片时，使用图片 API 搜索并下载 3 张相关图片用于上传（默认）
- 删除草稿：清理草稿箱（图文/视频/长文），支持预览/限量/全量删除
- 落盘与可追溯：`data/posts/<post_id>/` 保存 post / revision / execution / evidence

## 快速开始（推荐顺序）
```powershell
# 0) 创建并激活虚拟环境（首次）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 1) 安装依赖与浏览器（首次）
pip install -r requirements.txt
python -m playwright install chromium

# 2) 配置密钥（推荐用环境变量）
#   - ALIYUN_LLM_API_KEY：生成文案（推荐，Aliyun DeepSeek-V3.2）
#   - LLM_API_KEY：生成文案（可选：作为阿里云无额度时的备用）
#   - ALIYUN_IMAGE_API_KEY：生图（可与 LLM 共用同一把 DashScope Key）
#   - NEWS_API_KEY：每日新闻（可选；不配则回退到无需 key 的新闻源）
#   - PEXELS_API_KEY：自动配图（可选；不配则必须手动提供图片）
# 例如（PowerShell）：
#   $env:LLM_API_KEY="..."
#   $env:PEXELS_API_KEY="..."
#
# 3) 一键：生成 -> 校验/审批 -> 保存草稿（首次建议给更长登录时间）
.\.venv\Scripts\python -m apps.cli auto --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" --login-hold 600
```

## 草稿与浏览器 Profile
- 草稿箱数据保存在浏览器本地 profile 中，不同 profile 互不可见。
- 默认使用：`data/browser/chrome-profile`（复用 Chrome 渠道）。
- 若需自定义 profile，设置：
  - `XHS_BROWSER_CHANNEL=chrome`
  - `XHS_CHROME_USER_DATA_DIR=<profile 目录>`
  - `XHS_CHROME_PROFILE=Default`（或 `Profile 1` 等）

查看草稿（默认 profile）：
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" --profile-directory="Default1"
```

## 环境准备
```powershell
# 0) 创建虚拟环境（首次）
python -m venv .venv

# 1) 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 2) 安装依赖
pip install -r requirements.txt

# 3) 安装 Playwright 浏览器
python -m playwright install chromium
```

## Secrets / API Keys（不要提交到仓库）
- 本仓库已在 `.gitignore` 中忽略：`.env*`、`docs/*api-key.md` 等敏感文件。
- 推荐使用环境变量（更安全），或仅在本机创建 `docs/*api-key.md`（不要提交）。

LLM（生成文案）：
- 主用（阿里云百炼 / DashScope，DeepSeek-V3.2）：
  - 环境变量：`ALIYUN_LLM_API_KEY`（或 `ALIYUN_IMAGE_API_KEY` / `DASHSCOPE_API_KEY`）
  - 可选：`ALIYUN_LLM_MODEL`（默认 `deepseek-v3.2`）/ `ALIYUN_LLM_BASE_URL`（默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`）
- 备用（原 OpenAI 兼容提供商）：
  - 环境变量：`LLM_API_KEY`，可选 `LLM_MODEL` / `LLM_BASE_URL`
  - 或本机文件：复制 `docs/llm_api-key.example.md` 为 `docs/llm_api-key.md` 并填写
- 说明：若同时配置主用与备用，阿里云优先；当出现额度/限流/模型不可用等错误时自动回退

NewsAPI（“每日新闻”）：
- 环境变量：`NEWS_API_KEY`（或 `NEWSAPI_API_KEY`），可选 `NEWS_BASE_URL`
- 或本机文件：复制 `docs/news_api-key.example.md` 为 `docs/news_api-key.md` 并填写
- 无需 key 的免费新闻源：`GDELT`（设置 `NEWS_PROVIDER=gdelt` 或不配置 key 时自动回退）
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
1) 准备图片：放到 `assets/pics/*`；或配置 `PEXELS_API_KEY` 让系统在“无图”时自动配图
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
- `retry <post_id>`：对失败的 run 进行重试
- `delete-drafts`：删除草稿箱草稿（默认图文）

## 功能示例
### 1) 标题 + 简略提示词 + 图片齐全 → LLM 文案 → 保存草稿
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
.\.venv\Scripts\python -m apps.cli auto --title "冬日穿搭" --prompt "通勤简约风，给我3套搭配思路" --assets-glob "assets/pics/*" --login-hold 600
```

### 2) 标题为“每日新闻” → NewsAPI 获取当日新闻并按提示词挑选 → 保存草稿
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
$env:NEWS_API_KEY="YOUR_NEWS_API_KEY"
$env:NEWS_PROVIDER="newsapi"

# 有提示词：挑选最匹配 1 条新闻
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --prompt "美国时政" --assets-glob "assets/pics/*" --login-hold 600

# 无提示词：默认生成 1 条，可用 --count 调整
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --assets-glob "assets/pics/*" --login-hold 600
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --assets-glob "assets/pics/*" --count 3 --login-hold 600
```

### 3) 无图片上传 → Pexels 自动配图 → 保存草稿
前提：已配置 `PEXELS_API_KEY`（或本机 `docs/pexels_api-key.md`）。
```powershell
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
$env:PEXELS_API_KEY="YOUR_PEXELS_API_KEY"
$env:IMAGE_PROVIDER="pexels"
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
- `--count`：生成草稿数量（默认 1）
- `--assets-glob`：素材路径（glob），默认 `assets/pics/*`
- `--no-copy`：不复制素材到 `data/posts/<id>/assets`（默认会复制，便于隔离）
- `--login-hold`：等待手动登录的秒数（仅用于登录，不用于等待上传），默认 0
- `--wait-timeout`：等待发布页秒数，默认 300
- `--dry-run`：只抓取证据，不上传/不保存
- `--force`：忽略校验失败继续执行（仅排查用）

## create/run 常用参数
- `create`：`--assets-glob` / `--no-copy` / `--count`
- `run`：`--assets-glob` / `--login-hold` / `--wait-timeout` / `--dry-run` / `--force`

## 每日新闻（特殊标题）
- 当 `--title "每日新闻"`：会先拉取新闻候选，再生成草稿。
  - 生成条数由 `--count` 控制（默认 1）
  - 提供 `--prompt`：按提示词相关性排序后取前 N 条
  - 不提供 `--prompt`：按候选顺序取前 N 条
  - 正文会明确写出发布时间（提升时效性）
  - 正文开头新增“要点摘要：”20-40 字，概括新闻最重要部分（不评价）

可选配置（环境变量）：
- `NEWS_PROVIDER`：`newsapi` / `gdelt`（默认自动；有 `NEWS_API_KEY` 时优先 `newsapi`）
- `NEWS_TZ`：默认 `Asia/Shanghai`
- `NEWS_QUERY_DEFAULT`：提示词无结果时的回退 query（默认 `china`）

## 每日假新闻（特殊标题）
- 当 `--title "每日假新闻"`：使用 LLM 生成一条幽默、明显虚构的娱乐新闻，并保存草稿。
- 建议提供 `--prompt` 作为主题提示；正文会强制包含“本文纯属虚构，仅供娱乐。”。

## 提示词（Prompt）修改入口（代码位置）
为了方便你快速改“生成文案/每日新闻/每日假新闻/生图”的提示词，本项目所有核心提示词都集中在以下位置：

- 普通图文（标题/正文/topics 的 LLM 结构化输出）：`src/llm/generate.py` → `generate_draft()` → `ChatPromptTemplate.from_messages(...)`
  - `system`：整体写作风格、字数要求、JSON 输出要求等
  - `user`：把 `prompt_hint/title_hint/assets` 注入模型
- 每日新闻（给 LLM 的“新闻写作提示词”）：`src/workflow/create_post.py` → `_daily_news_prompt(...)`
  - 同文件：`_daily_news_offline_body(...)` / `_ensure_daily_news_sections(...)`（离线兜底与段落结构修正）
- 每日假新闻（给 LLM 的“虚构新闻提示词”）：`src/workflow/create_post.py` → `_fake_news_prompt(...)`
  - 同文件：`_fake_news_offline_body(...)`（离线兜底）
- 阿里云百炼文生图（把主题/要点拼成生图提示词）：`src/images/auto_image.py` → `_build_aliyun_image_prompt(...)`
  - 同文件：`build_image_query(...)`（用于检索/补图时的 query 生成；影响“相关性”）
  - 可选负面提示词（negative prompt）与自动扩写：`src/images/aliyun_images.py`（读取环境变量 `ALIYUN_IMAGE_NEGATIVE_PROMPT` / `ALIYUN_IMAGE_PROMPT_EXTEND`）

## 自动配图（无图片时）
- 当 `--assets-glob` 未命中任何图片：会自动生成/下载图片到 `data/posts/<post_id>/assets/`，然后继续上传并保存草稿。
- 通过 `IMAGE_PROVIDER` 选择来源：
  - `pexels`（默认）：图片检索下载（需要 `PEXELS_API_KEY`）
  - `aliyun`：阿里云百炼（DashScope）API 生图并落盘（支持 Qwen-Image / Z-Image / 通义万相 wan2.x/wanx 系列）
- 调整张数：`AUTO_IMAGE_COUNT=3`（上限 18；`pexels` 默认 3，`aliyun` 默认 1）。
- 提高相关性：`IMAGE_MIN_SCORE=0.12`（分数越高越严格，图片数量可能减少）。
- 关闭自动配图：`AUTO_IMAGE=0`（注意：图文 post 仍需要至少 1 张图片，否则校验会失败）。

### 阿里云百炼 / DashScope（API 生图，推荐）配置
前提：你已在本机准备好阿里云百炼 API Key（本仓库不会提交密钥）。

配置方式（二选一）：
- 推荐：环境变量 `ALIYUN_IMAGE_API_KEY`
- 或本机文件：复制 `docs/aliyun_image_api-key.example.md` 为 `docs/aliyun_image_api-key.md` 并填写（已被 `.gitignore` 忽略）

支持模型（文生图，模型名以百炼控制台为准，均使用同一把 API Key）：
- Qwen-Image：`qwen-image-plus-2026-01-09` / `qwen-image-max` / `qwen-image`
- Z-Image：`z-image-turbo`
- 通义万相：`wan2.6-t2i` / `wan2.6-image` / `wan2.5-t2i-preview` / `wanx2.1-t2i-turbo` 等
- 说明：本流程仅使用“文生图”模型；`i2v`/`t2v`/`edit`/`mt-image` 会被自动跳过

常用可选参数（环境变量）：
- `ALIYUN_IMAGE_MODELS`：生图模型候选列表（逗号/空格分隔，按顺序尝试；优先于 `ALIYUN_IMAGE_MODEL`）
- `ALIYUN_IMAGE_MODEL`：生图模型（默认 `qwen-image-plus-2026-01-09`；仅在未设置 `ALIYUN_IMAGE_MODELS` 时使用）
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
- 阿里云生图模型列表：支持 `ALIYUN_IMAGE_MODELS` 按顺序尝试与回退
- 生图事件摘要：LLM 输出 `image_event`（约 30 字）用于降低“新闻海报感/文字”概率
- 生图提示词收敛：仅用事件描述生成插画，避免“报道/海报/采访”等语义
- 元数据完整落盘：每条 post 保存 news/image/attempt 等字段，便于追踪与复盘
- 每日新闻要点摘要：正文首行输出 20-40 字关键摘要，突出新闻要点

## 一键快速使用（免费额度版本）
```powershell
# 仅需配置阿里云 Key（用于 LLM + 生图）
$env:ALIYUN_LLM_API_KEY="YOUR_DASHSCOPE_KEY"
$env:ALIYUN_IMAGE_API_KEY="YOUR_DASHSCOPE_KEY"
$env:NEWS_PROVIDER="gdelt"
$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_MODELS="qwen-image-plus-2026-01-09,qwen-image-max,qwen-image,wan2.6-t2i,wan2.6-image,z-image-turbo"

.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 10 --assets-glob "empty/pics/*" --login-hold 600 --wait-timeout 600
```


**每日新闻一行版（无本地图片 → 阿里云生图 → 保存草稿）**
```powershell
$env:IMAGE_PROVIDER="aliyun"; $env:ALIYUN_IMAGE_MODELS="qwen-image-plus-2026-01-09,qwen-image-max,qwen-image,wan2.6-t2i,wan2.6-image,z-image-turbo"; $env:ALIYUN_IMAGE_SIZE="1104*1472"; $env:ALIYUN_IMAGE_TIMEOUT_S="180"; $env:ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S="60"; $env:ALIYUN_IMAGE_MAX_ATTEMPTS="3"; .\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 3 --assets-glob "empty/pics/*" --login-hold 600 --wait-timeout 600
```

**每日假新闻一行版（无本地图片 → 阿里云生图 → 保存草稿）**
```powershell
$env:IMAGE_PROVIDER="aliyun"; $env:ALIYUN_IMAGE_MODELS="qwen-image-plus-2026-01-09,qwen-image-max,qwen-image,wan2.6-t2i,wan2.6-image,z-image-turbo"; $env:ALIYUN_IMAGE_SIZE="1104*1472"; $env:ALIYUN_IMAGE_TIMEOUT_S="180"; $env:ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S="60"; $env:ALIYUN_IMAGE_MAX_ATTEMPTS="3"; .\.venv\Scripts\python -m apps.cli auto --title "每日假新闻" --prompt "火星快递导致地球外卖迟到" --count 1 --assets-glob "empty/pics/*" --login-hold 600 --wait-timeout 600
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
- 草稿箱为空：确认打开的是保存草稿时用的同一个 profile（不同 profile 草稿互不可见）。
- 没看到“图文笔记”：只运行了 `create` 不会出现在网页草稿箱；需要 `auto` 或 `approve + run`。
- Playwright 启动失败：关闭所有 Chrome 窗口，避免 profile 被占用。
- 看到 “offline fallback”：说明 LLM 调用失败，请检查 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 是否可用。

## 相关文档（docs）
- `docs/工作流新闻任务书.md`
- `docs/图片查找功能.md`
- `docs/增加图片api后的错误修正任务书.md`
- `docs/新闻要点摘要任务书.md`
- `docs/新闻时效性去重与内容规范任务书.md`
- `docs/中国海外新闻比例任务书.md`
