# Auto Redbook Workflow

本项目用于在本地生成小红书图文内容，并通过 Playwright 自动保存为草稿（不发布）。

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

## 常见问题
- 草稿箱为空：确认打开的是保存草稿时用的同一个 profile。
- Playwright 启动失败：关闭所有 Chrome 窗口，避免 profile 被占用。

## CLI 使用
验证/审批/保存草稿：
```powershell
python -m apps.cli validate <post_id>
python -m apps.cli approve <post_id>
python -m apps.cli run <post_id> --login-hold 60
python -m apps.cli retry <post_id>
```

一键流程（生成 -> 验证/审批 -> 保存草稿）：
```powershell
python -m apps.cli auto --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*" --login-hold 60
```

## auto 参数说明
- `--title`：标题（必填）
- `--prompt`：提示词（可选）
- `--assets-glob`：素材路径（glob），默认 `assets/pics/*`
- `--login-hold`：等待登录秒数，默认 0
- `--wait-timeout`：等待发布页秒数，默认 300
- `--dry-run`：只抓取证据，不上传/不保存
- `--force`：忽略校验失败继续执行（仅排查用）

## 每日新闻（特殊标题）
- 当 `--title "每日新闻"`：会先拉取当日新闻，再生成草稿。
  - 提供 `--prompt`：挑选最符合提示词的 1 条新闻生成 1 条草稿
  - 不提供 `--prompt`：随便挑选 3 条新闻，生成并保存 3 条草稿

## 草稿保存流程（手动分步）
```powershell
# 1) 生成内容
python -m apps.cli create --title "标题" --prompt "提示词（可选）" --assets-glob "assets/pics/*"

# 2) 登录保持（首用）
python -m apps.cli run <post_id> --login-hold 600 --dry-run

# 3) 保存草稿
python -m apps.cli run <post_id> --login-hold 60
```
