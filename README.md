# Auto Redbook Workflow

本项目用于在本地生成小红书图文内容，并通过 Playwright 自动保存为草稿（不发布）。

## 功能一览
- 普通图文：`标题 + 提示词（可选） + 图片（可选）` → 生成草稿并保存到草稿箱
- 特殊标题「每日新闻」：自动抓取新闻 → 生成草稿并保存
- 自动配图：当未提供图片时，使用图片 API 搜索并下载 1 张相关图片用于上传
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
python -m apps.cli auto --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" --login-hold 600
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
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" --profile-directory="Default"
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
- 环境变量：`PEXELS_API_KEY`，可选 `PEXELS_BASE_URL`；`AUTO_IMAGE=0` 可关闭自动配图
- 或本机文件：复制 `docs/pexels_api-key.example.md` 为 `docs/pexels_api-key.md` 并填写

如曾泄露密钥：请立即在对应平台轮换/作废旧 key。

## 使用顺序（推荐）
推荐直接使用 `auto` 一键完成：
1) 准备图片：放到 `assets/pics/*`；或配置 `PEXELS_API_KEY` 让系统在“无图”时自动配图
2) 首次登录：运行时把 `--login-hold` 设大一些（例如 600 秒）用于扫码登录
3) 执行一键保存草稿：

```powershell
python -m apps.cli auto --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" --login-hold 600
```

## 使用顺序（手动分步）
需要更可控/便于排查时按以下顺序：
```powershell
# 1) 生成内容并落盘（输出 post_id）
python -m apps.cli create --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*"

# 2) 校验（可选）
python -m apps.cli validate <post_id>

# 3) 审批（标记为 approved）
python -m apps.cli approve <post_id>

# 4) 保存草稿（首次建议加长 login_hold）
python -m apps.cli run <post_id> --login-hold 600

# 5) 失败后重试
python -m apps.cli retry <post_id>
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

## auto 参数说明
- `--title`：标题（必填）
- `--prompt`：提示词（可选）
- `--assets-glob`：素材路径（glob），默认 `assets/pics/*`
- `--no-copy`：不复制素材到 `data/posts/<id>/assets`（默认会复制，便于隔离）
- `--login-hold`：等待登录秒数，默认 0
- `--wait-timeout`：等待发布页秒数，默认 300
- `--dry-run`：只抓取证据，不上传/不保存
- `--force`：忽略校验失败继续执行（仅排查用）

## create/run 常用参数
- `create`：`--assets-glob` / `--no-copy`
- `run`：`--assets-glob` / `--login-hold` / `--wait-timeout` / `--dry-run` / `--force`

## 每日新闻（特殊标题）
- 当 `--title "每日新闻"`：会先拉取新闻候选，再生成草稿。
  - 提供 `--prompt`：按提示词挑选最匹配的 1 条新闻生成 1 条草稿
  - 不提供 `--prompt`：挑选 3 条新闻，生成并保存 3 条草稿

可选配置（环境变量）：
- `NEWS_PROVIDER`：`newsapi` / `gdelt`（默认自动；有 `NEWS_API_KEY` 时优先 `newsapi`）
- `NEWS_TZ`：默认 `Asia/Shanghai`
- `NEWS_QUERY_DEFAULT`：提示词无结果时的回退 query（默认 `china`）

## 自动配图（无图片时）
- 当 `--assets-glob` 未命中任何图片：会自动从 Pexels 搜索并下载 1 张图片到 `data/posts/<post_id>/assets/`，然后继续上传并保存草稿。
- 关闭自动配图：`AUTO_IMAGE=0`（注意：图文 post 仍需要至少 1 张图片，否则校验会失败）。

## 输出位置（落盘）
- `data/posts/<post_id>/post.json`：草稿内容与元数据（含 `platform.news` / `platform.image`）
- `data/posts/<post_id>/revisions/*.json`：每次生成的 revision
- `data/posts/<post_id>/executions/*.json`：每次保存草稿 attempt 的执行记录
- `data/posts/<post_id>/evidence/<execution_id>/`：截图/HTML 等证据文件

## 调试（可选）
仅用于打开发布页/保持登录（不上传/不保存）：
```powershell
python -m apps.cli run <post_id> --login-hold 600 --dry-run --force
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
