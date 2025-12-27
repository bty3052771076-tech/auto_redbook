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
python -m apps.cli auto --title "标题" --prompt "提示词" --assets-glob "assets/pics/*" --login-hold 60
```

## auto 参数说明
- `--title`：标题（必填）
- `--prompt`：提示词（必填）
- `--assets-glob`：素材路径（glob），默认 `assets/pics/*`
- `--login-hold`：等待登录秒数，默认 0
- `--wait-timeout`：等待发布页秒数，默认 300
- `--dry-run`：只抓取证据，不上传/不保存
- `--force`：忽略校验失败继续执行（仅排查用）

## 草稿保存流程（手动分步）
```powershell
# 1) 生成内容
python -m apps.cli create --title "标题" --prompt "提示词" --assets-glob "assets/pics/*"

# 2) 登录保持（首用）
python -m apps.cli run <post_id> --login-hold 600 --dry-run

# 3) 保存草稿
python -m apps.cli run <post_id> --login-hold 60
```
