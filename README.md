# Auto Redbook Workflow

本项目用于在本地生成小红书图文内容，并通过 Playwright 自动保存为草稿（不发布）。

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
#   - LLM_API_KEY：生成文案（必填）
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
- 环境变量：`LLM_API_KEY`（必填），可选 `LLM_MODEL` / `LLM_BASE_URL`
- 或本机文件：复制 `docs/llm_api-key.example.md` 为 `docs/llm_api-key.md` 并填写

NewsAPI（“每日新闻”）：
- 环境变量：`NEWS_API_KEY`（或 `NEWSAPI_API_KEY`），可选 `NEWS_BASE_URL`
- 或本机文件：复制 `docs/news_api-key.example.md` 为 `docs/news_api-key.md` 并填写

Pexels（自动配图：当未提供图片素材时）：
- 环境变量：`PEXELS_API_KEY`，可选 `PEXELS_BASE_URL` / `AUTO_IMAGE_COUNT` / `IMAGE_MIN_SCORE`；`AUTO_IMAGE=0` 可关闭自动配图
- 或本机文件：复制 `docs/pexels_api-key.example.md` 为 `docs/pexels_api-key.md` 并填写

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

可选配置（环境变量）：
- `NEWS_PROVIDER`：`newsapi` / `gdelt`（默认自动；有 `NEWS_API_KEY` 时优先 `newsapi`）
- `NEWS_TZ`：默认 `Asia/Shanghai`
- `NEWS_QUERY_DEFAULT`：提示词无结果时的回退 query（默认 `china`）

## 每日假新闻（特殊标题）
- 当 `--title "每日假新闻"`：使用 LLM 生成一条幽默、明显虚构的娱乐新闻，并保存草稿。
- 建议提供 `--prompt` 作为主题提示；正文会强制包含“本文纯属虚构，仅供娱乐。”。

## 自动配图（无图片时）
- 当 `--assets-glob` 未命中任何图片：会自动生成/下载图片到 `data/posts/<post_id>/assets/`，然后继续上传并保存草稿。
- 通过 `IMAGE_PROVIDER` 选择来源：
  - `pexels`（默认）：图片检索下载（需要 `PEXELS_API_KEY`）
  - `chatgpt_images`：进入 `https://chatgpt.com/images` 自动生图并落盘（优先下载原图字节，避免“截图截到模糊/生成中”）
- 调整张数：`AUTO_IMAGE_COUNT=3`（上限 18；`pexels` 默认 3，`chatgpt_images` 默认 1）。
- 提高相关性：`IMAGE_MIN_SCORE=0.12`（分数越高越严格，图片数量可能减少）。
- 关闭自动配图：`AUTO_IMAGE=0`（注意：图文 post 仍需要至少 1 张图片，否则校验会失败）。

### ChatGPT Images（自动生图）配置
前提：你已经在下面这个 profile 中登录了 ChatGPT：
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" --profile-directory="Default1"
```

运行前建议关闭所有 Chrome 窗口（避免 profile 被占用）。

注意：ChatGPT 站点可能触发 Cloudflare 人机校验，自动化无法绕过；如果自动化窗口一直卡在白屏/加载中，通常就是被拦截了。
默认行为是在等待 `CHATGPT_CHALLENGE_TIMEOUT_S` 后，自动切换到【手动生图】模式：用“普通 Chrome 窗口”打开 `https://chatgpt.com/images`，你粘贴提示词生成并把下载图片放到 `data/posts/<post_id>/assets/`，脚本检测到新图片后继续保存草稿。

如果你希望尽量“全自动”（避免重新启动浏览器触发校验），可以改用【连接到你已打开的 Chrome】模式：你先用普通 Chrome 打开并通过校验，然后脚本通过 CDP 连接并复用当前页面。

```powershell
$env:IMAGE_PROVIDER="chatgpt_images"
$env:CHATGPT_CHROME_EXECUTABLE="C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:CHATGPT_CHROME_USER_DATA_DIR="D:\AI\codex\redbook_workflow\data\browser\chrome-profile"
$env:CHATGPT_CHROME_PROFILE="Default1"
$env:CHATGPT_IMAGE_TIMEOUT_S="180"             # 生成图片等待上限（秒）
$env:CHATGPT_DOWNLOAD_TIMEOUT_S="180"          # 等待原图可下载的最大时间（越大越稳，但更慢）
$env:CHATGPT_CHALLENGE_TIMEOUT_S="30"          # 自动化被拦截后等待 N 秒再转手动
$env:CHATGPT_MANUAL_TIMEOUT_S="1800"           # 手动模式等待你放入图片的时间
$env:CHATGPT_FALLBACK_MANUAL_ON_CHALLENGE="1"  # 0=关闭手动降级（保持失败）

.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --prompt "美国时政" --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600
```

### 连接到已打开的 Chrome（可选，推荐）
1) 先用下面命令启动 Chrome（会启用远程调试端口），并打开 ChatGPT Images：
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" `
  --profile-directory="Default1" `
  "https://chatgpt.com/images"
```
如果你本机已经有其它 Chrome 在运行，上面的命令可能会“复用已有进程”而导致 `9222` 端口没有真的打开；建议先完全退出所有 `chrome.exe` 再运行。
2) 在该窗口里手动通过 Cloudflare/确认页面正常后，不要关闭该窗口。
3) 另开一个终端运行（脚本会连接到现有 Chrome）：
```powershell
$env:CHATGPT_CDP_URL="http://127.0.0.1:9222"
$env:XHS_CDP_URL="http://127.0.0.1:9222"
.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --prompt "美国时政" --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600
```

**完整指令（GPT 生图 → 保存到小红书草稿）**
```powershell
# 1) 先启动已登录的 Chrome（复用你的 Default1 profile）
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" `
  --profile-directory="Default1" `
  "https://chatgpt.com/images"

# 2) 通过校验后保持窗口打开，再运行自动化（无本地图片 → ChatGPT 生图 → 保存草稿）
$env:IMAGE_PROVIDER="chatgpt_images"
$env:CHATGPT_CDP_URL="http://127.0.0.1:9222"
$env:XHS_CDP_URL="http://127.0.0.1:9222"
$env:CHATGPT_IMAGE_TIMEOUT_S="180"
$env:CHATGPT_DOWNLOAD_TIMEOUT_S="180"

.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 3 --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600
```

**一行版（含人工回车等待）**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" --profile-directory="Default1" "https://chatgpt.com/images"; Read-Host "完成校验后回车继续"; $env:IMAGE_PROVIDER="chatgpt_images"; $env:CHATGPT_CDP_URL="http://127.0.0.1:9222"; $env:XHS_CDP_URL="http://127.0.0.1:9222"; $env:CHATGPT_IMAGE_TIMEOUT_S="180"; $env:CHATGPT_DOWNLOAD_TIMEOUT_S="180"; $env:CHATGPT_CHALLENGE_TIMEOUT_S="180"; $env:CHATGPT_MANUAL_TIMEOUT_S="180"; .\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 3 --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600
```

**每日假新闻（GPT 生图 → 保存到小红书草稿）**
```powershell
# 1) 先启动已登录的 Chrome（复用你的 Default1 profile）
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" `
  --profile-directory="Default1" `
  "https://chatgpt.com/images"

# 2) 通过校验后保持窗口打开，再运行自动化（无本地图片 → ChatGPT 生图 → 保存草稿）
$env:IMAGE_PROVIDER="chatgpt_images"
$env:CHATGPT_CDP_URL="http://127.0.0.1:9222"
$env:XHS_CDP_URL="http://127.0.0.1:9222"
$env:CHATGPT_IMAGE_TIMEOUT_S="180"
$env:CHATGPT_DOWNLOAD_TIMEOUT_S="180"

.\.venv\Scripts\python -m apps.cli auto --title "每日假新闻" --prompt "火星快递导致地球外卖迟到" --count 1 --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600
```

**每日假新闻一行版（含人工回车等待）**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" --profile-directory="Default1" "https://chatgpt.com/images"; Read-Host "完成校验后回车继续"; $env:IMAGE_PROVIDER="chatgpt_images"; $env:CHATGPT_CDP_URL="http://127.0.0.1:9222"; $env:XHS_CDP_URL="http://127.0.0.1:9222"; $env:CHATGPT_IMAGE_TIMEOUT_S="180"; $env:CHATGPT_DOWNLOAD_TIMEOUT_S="180"; $env:CHATGPT_CHALLENGE_TIMEOUT_S="180"; $env:CHATGPT_MANUAL_TIMEOUT_S="180"; .\.venv\Scripts\python -m apps.cli auto --title "每日假新闻" --prompt "火星快递导致地球外卖迟到" --count 1 --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600
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

探测 ChatGPT Images 登录态/输入框（会自动留证到 `data/posts/<post_id>/evidence/...`）：
```powershell
.\.venv\Scripts\python -m apps.inspect_chatgpt_images --hold 30
```

E2E 测试（推荐先用 CDP 模式打开并通过校验）：
```powershell
# 只测 ChatGPT Images 生图落盘（验证 method != screenshot*）
.\.venv\Scripts\python -m apps.e2e_test_chatgpt_images --prompt "为一条科技类新闻生成竖版3:4新闻插画，干净无文字无logo，抽象象征元素，高清"

# 全流程：每日新闻 -> ChatGPT 生图 -> 小红书保存草稿（会自动读取 post.json 校验 method/素材落盘）
.\.venv\Scripts\python -m apps.e2e_test_auto_full --cdp "http://127.0.0.1:9222" --title "每日新闻" --prompt "美国时政" --count 1 --assets-glob "empty/pics/*"
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
