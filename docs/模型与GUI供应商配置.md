# 模型与 GUI 供应商配置

更新时间：2026-06-19

本文说明图形化自动发帖界面中的供应商、模型选项，以及它们最终注入 CLI 子进程的环境变量。

## GUI 入口

推荐双击轻量启动器：

```powershell
.\AutoRedbookGUI-Launcher.exe
```

如果还没有生成 launcher：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_gui_exe.ps1
```

脚本入口：

```powershell
.\Start-GUI.cmd
```

源码入口：

```powershell
.\.venv\Scripts\python.exe -m apps.gui
```

旧的 `AutoRedbookGUI.exe` 是历史打包产物，不再推荐使用；新版 launcher 只负责启动当前工作区的设计版 GUI。

新版 GUI 采用“发布控制台”布局：

- `自动发帖`：一键执行 `create -> approve -> run`，并在同一界面选择 LLM 供应商、LLM 模型、配图来源和阿里云生图模型。
- `仅生成`：只生成本地草稿，便于检查文案和图片。
- `草稿处理`：对已有帖子执行审核、上传和保存草稿；列表按“标题 + 状态 + post_id”显示最近帖子，避免只看到一串 id。
- `删除草稿`：预览或删除小红书草稿箱草稿。
- `配置`：保存本机 `.env.gui`，用于密钥和默认参数。

`.env.gui` 只保存在当前工作区，已被 `.gitignore` 忽略，不应提交。

## LLM 供应商

GUI 支持三个选项：

| 供应商 | 用途 | 主要环境变量 |
|---|---|---|
| `aliyun` | 只使用阿里云百炼 / DashScope OpenAI 兼容接口 | `LLM_PROVIDER=aliyun`, `DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`, `ALIYUN_LLM_MODEL` |
| `ppinfra` | 只使用 ppinfra OpenAI 兼容接口 | `LLM_PROVIDER=ppinfra`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` |
| `auto` | 阿里云优先，失败后使用 ppinfra 备用 | `LLM_PROVIDER=auto`, 同时配置阿里云和 ppinfra key |

### 阿里云免费 LLM 模型选项

GUI 内置以下阿里云免费模型选项，默认首选 `qwen3.7-plus`：

```text
qwen3.7-plus
deepseek-v4-flash
qwen3.6-flash-2026-04-16
qwen3.6-35b-a3b
qwen3.7-max-2026-05-17
qwen3.7-max-2026-06-08
glm-5.1
qwen3.6-plus-2026-04-02
qwen3.7-max-preview
glm-5.2
qwen3.6-plus
qwen3.5-plus-2026-04-20
qwen3.6-max-preview
qwen3.7-max
kimi-k2.6
qwen3.7-max-2026-05-20
qwen3.7-plus-2026-05-26
qwen3.6-flash
```

如果选择单个阿里云模型，GUI 会注入：

```powershell
LLM_PROVIDER=aliyun
ALIYUN_LLM_MODEL=<所选模型>
ALIYUN_LLM_MODELS=<所选模型>
ALIYUN_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

如果选择 `auto` 且模型为“阿里云免费模型列表（顺序回退）”，GUI 会把全部阿里云免费模型写入 `ALIYUN_LLM_MODELS`，按顺序尝试。

### ppinfra 模型选项

当前 ppinfra 默认模型：

```text
deepseek/deepseek-v3-0324
```

如果选择 ppinfra，GUI 会注入：

```powershell
LLM_PROVIDER=ppinfra
LLM_MODEL=deepseek/deepseek-v3-0324
LLM_BASE_URL=https://api.ppinfra.com/openai
```

## 图片供应商

| 供应商 | 用途 | 主要环境变量 |
|---|---|---|
| `pexels` | 搜索并下载图库图片，适合作为稳定默认项 | `IMAGE_PROVIDER=pexels`, `PEXELS_API_KEY` |
| `aliyun` | 使用阿里云百炼 / DashScope 文生图 | `IMAGE_PROVIDER=aliyun`, `DASHSCOPE_API_KEY` 或 `ALIYUN_IMAGE_API_KEY`, `ALIYUN_IMAGE_MODEL` |

### 阿里云生图模型选项

GUI 内置以下阿里云生图模型：

```text
wan2.7-image
wan2.7-image-pro
```

默认模型为 `wan2.7-image`。如果选择阿里云配图，GUI 会注入：

```powershell
IMAGE_PROVIDER=aliyun
ALIYUN_IMAGE_MODEL=<所选模型>
ALIYUN_IMAGE_MODELS=<所选模型>
```

`wan2.7-image` 和 `wan2.7-image-pro` 使用阿里云万相 2.7 图像生成与编辑接口；本项目的自动配图流程只走“文生图”，不会传入参考图或编辑框。

## 推荐组合

稳定少折腾：

```text
LLM 供应商：aliyun
LLM 模型：qwen3.7-plus
配图来源：pexels
```

全部使用阿里云免费额度：

```text
LLM 供应商：aliyun
LLM 模型：qwen3.7-plus
配图来源：aliyun
阿里云生图模型：wan2.7-image
```

阿里云优先、ppinfra 兜底：

```text
LLM 供应商：auto
LLM 模型：阿里云免费模型列表（顺序回退）
配图来源：pexels 或 aliyun
```

## CLI 等价配置示例

阿里云 LLM + 阿里云生图：

```powershell
$env:DASHSCOPE_API_KEY="YOUR_DASHSCOPE_KEY"
$env:LLM_PROVIDER="aliyun"
$env:ALIYUN_LLM_MODEL="qwen3.7-plus"
$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_MODEL="wan2.7-image"
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*" --login-hold 600
```

ppinfra LLM + Pexels 配图：

```powershell
$env:LLM_PROVIDER="ppinfra"
$env:LLM_API_KEY="YOUR_PPINFA_KEY"
$env:LLM_MODEL="deepseek/deepseek-v3-0324"
$env:PEXELS_API_KEY="YOUR_PEXELS_KEY"
$env:IMAGE_PROVIDER="pexels"
.\.venv\Scripts\python.exe -m apps.cli auto --title "上海周末咖啡馆推荐" --prompt "安静，适合学习办公" --assets-glob "assets/empty/*" --login-hold 600
```

## 注意事项

- GUI 只把供应商和模型选择注入当前子进程；不会修改 `docs/*api-key.md`。
- API key 是否有额度，最终仍以各供应商控制台账单/额度页为准；本项目只能通过最小请求做可用性探测。
- `wan2.7-image-pro` 支持更高规格，但通常更慢，也更容易消耗额度；批量发帖时建议先用 `wan2.7-image` 小规模验证。
- 若没有本地图片，`assets-glob` 可以指向空目录，例如 `assets/empty/*`，让系统自动配图。
