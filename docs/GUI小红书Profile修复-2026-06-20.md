# GUI 小红书 Profile 修复说明（2026-06-20）

## 问题

GUI 顶部按钮“打开小红书创作平台”原来使用 `webbrowser.open()` 打开链接，会进入系统默认浏览器或默认 Chrome profile。小红书草稿和登录态保存在浏览器 profile 中，因此这会导致打开的账号/profile 与自动化发布使用的 profile 不一致。

正确的工作区 profile 是：

```text
data/browser/chrome-profile
```

## 修复

- `apps.gui.open_xhs_creator()` 改为优先启动本机 Chrome，并显式传入 `--user-data-dir=<工作区>/data/browser/chrome-profile`。
- `scripts/open_xhs_creator.ps1` 与 GUI 使用一致的 profile 规则。
- 找不到 Chrome 时，保留系统默认浏览器兜底打开链接，但此时可能不是正确 profile。

## 可选覆盖变量

```powershell
$env:XHS_CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:XHS_CHROME_USER_DATA_DIR="E:\AI\codex\redbook_workflow\data\browser\chrome-profile"
$env:XHS_CHROME_PROFILE="Default"
```

通常不需要设置这些变量。只有在 Chrome 安装位置特殊，或确实要切换到其他 profile 时才设置。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gui.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\open_xhs_creator.ps1
```

打开后应看到同一个小红书登录账号和同一批草稿。如果看不到，请先确认没有手动切换到其他 Chrome profile。
