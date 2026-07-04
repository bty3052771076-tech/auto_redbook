# 模型与 GUI 供应商配置

更新时间：2026-07-03

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

- `自动发帖`：一键执行“生成 -> 校验 -> 保存草稿”，并在同一界面选择 LLM 供应商、LLM 模型、配图来源、生图模型和每日新闻评价视角。
- `草稿处理`：对已有帖子执行审核、上传和保存草稿；列表按“标题 + 状态 + post_id”显示最近帖子，时间在独立框中按北京时间展示，避免只看到一串 id 或混在同一行。
- `删除草稿`：预览或删除小红书草稿箱草稿。
- `配置`：保存本机 `.env.gui`，用于密钥和默认参数；也提供阿里云百炼与火山引擎 Ark 的免费额度查询按钮。

2026-07-01 起，GUI 不再暴露“仅生成”页签，CLI 也不再注册公开的 `create` 命令。常规使用请直接走 `自动发帖` 或 `apps.cli auto` 保存到小红书创作者中心草稿箱。

`.env.gui` 只保存在当前工作区，已被 `.gitignore` 忽略，不应提交。

每日新闻的 `评价视角` 默认是 `无视角评价`。GUI 会把该值传给 CLI 的 `--evaluation-viewpoint`，用于写入 LLM 提示词；默认不预设国家、行业、投资者或平台立场，自定义视角也仍然要求基于新闻事实客观评价。

## LLM 供应商

GUI 支持四个选项：

| 供应商 | 用途 | 主要环境变量 |
|---|---|---|
| `aliyun` | 只使用阿里云百炼 / DashScope OpenAI 兼容接口 | `LLM_PROVIDER=aliyun`, `DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`, `ALIYUN_LLM_MODEL` |
| `volcengine` | 只使用火山引擎方舟 / Ark OpenAI 兼容接口 | `LLM_PROVIDER=volcengine`, `VOLCENGINE_API_KEY`, `VOLCENGINE_LLM_MODEL` |
| `ppinfra` | 只使用 ppinfra OpenAI 兼容接口 | `LLM_PROVIDER=ppinfra`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` |
| `auto` | 阿里云、火山引擎、ppinfra 按配置顺序回退 | `LLM_PROVIDER=auto`, 同时配置对应供应商 key |

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

### 火山引擎 Ark LLM 模型选项

GUI 内置以下火山引擎 Ark LLM 选项，默认首选 `doubao-seed-2-1-turbo-260628`：

```text
doubao-seed-2-1-turbo-260628
doubao-seed-2-1-pro-260628
doubao-seed-2-0-pro-260215
doubao-seed-2-0-lite-260428
doubao-seed-2-0-mini-260428
doubao-seed-1-8-251228
doubao-seed-1-6-251015
doubao-seed-1-6-250615
doubao-seed-1-6-flash-250828
doubao-seed-1-6-flash-250615
doubao-seed-code-preview-251028
doubao-seed-2-0-code-preview-260215
doubao-seed-character-260628
doubao-seed-character-251128
doubao-seed-translation-250915
glm-5.2
deepseek-v4-pro
deepseek-v4-flash
deepseek-v4-flash-260425
deepseek-v4-pro-260425
deepseek-v3-2-251201
glm-4-7-251222
glm-4-5-air-20250728
qwen3-32b-20250429
qwen3-14b-20250429
qwen3-8b-20250429
qwen3-0-6b-20250429
```

如果选择单个火山引擎模型，GUI 会注入：

```powershell
LLM_PROVIDER=volcengine
VOLCENGINE_LLM_MODEL=<所选模型>
VOLCENGINE_LLM_MODELS=<所选模型>
VOLCENGINE_LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

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
| `aliyun` | 使用阿里云百炼 / DashScope 文生图，当前 GUI 默认项 | `IMAGE_PROVIDER=aliyun`, `DASHSCOPE_API_KEY` 或 `ALIYUN_IMAGE_API_KEY`, `ALIYUN_IMAGE_MODEL` |
| `volcengine` | 使用火山引擎方舟 / Seedream 文生图 | `IMAGE_PROVIDER=volcengine`, `VOLCENGINE_API_KEY`, `VOLCENGINE_IMAGE_MODEL`, `VOLCENGINE_IMAGE_SIZE` |
| `pexels` | 搜索并下载图库图片，可作为无生图额度时的备用 | `IMAGE_PROVIDER=pexels`, `PEXELS_API_KEY` |

### 阿里云生图模型选项

GUI 内置以下阿里云生图模型：

```text
wan2.7-image
wan2.7-image-pro
qwen-image-2.0-pro-2026-06-22
qwen-image-2.0-pro-2026-04-22
```

默认模型为 `wan2.7-image`。如果选择阿里云配图，GUI 会注入：

```powershell
IMAGE_PROVIDER=aliyun
ALIYUN_IMAGE_MODEL=<所选模型>
ALIYUN_IMAGE_MODELS=<所选模型>
```

`wan2.7-image` 和 `wan2.7-image-pro` 使用阿里云万相 2.7 图像生成与编辑接口；本项目的自动配图流程只走“文生图”，不会传入参考图或编辑框。
`qwen-image-2.0-pro-2026-06-22` 与 `qwen-image-2.0-pro-2026-04-22` 已加入 GUI 下拉列表，供手动测试；默认模型仍保持 `wan2.7-image`，避免影响现有批量自动发帖。

### 火山引擎 Seedream 生图模型选项

GUI 内置以下火山引擎 Seedream 模型，默认首选 `doubao-seedream-5-0-lite-260128`：

```text
doubao-seedream-5-0-lite-260128
doubao-seedream-5-0-260128
doubao-seedream-4-5-251128
doubao-seedream-4-0-250828
```

如果选择火山引擎配图，GUI 会注入：

```powershell
IMAGE_PROVIDER=volcengine
VOLCENGINE_IMAGE_MODEL=<所选模型>
VOLCENGINE_IMAGE_MODELS=<所选模型>
VOLCENGINE_IMAGE_SIZE=1440x2560
```

`doubao-seedream-5-0-lite-260128` 对图片像素数有下限要求，项目默认使用 `1440x2560`。

## 推荐组合

推荐默认：

```text
LLM 供应商：aliyun
LLM 模型：qwen3.7-plus
配图来源：aliyun
阿里云生图模型：wan2.7-image
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
配图来源：aliyun（默认）或 pexels
```

火山引擎验证组合：

```text
LLM 供应商：volcengine
LLM 模型：glm-5.2 / deepseek-v4-pro / deepseek-v4-flash / doubao-seed-2-1-turbo-260628
配图来源：volcengine
火山引擎生图模型：doubao-seedream-5-0-lite-260128
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

火山引擎 LLM + Seedream 配图：

```powershell
$env:VOLCENGINE_API_KEY="YOUR_ARK_KEY"
$env:LLM_PROVIDER="volcengine"
$env:VOLCENGINE_LLM_MODEL="glm-5.2"
$env:VOLCENGINE_LLM_MODELS="glm-5.2"
$env:IMAGE_PROVIDER="volcengine"
$env:VOLCENGINE_IMAGE_MODEL="doubao-seedream-5-0-lite-260128"
$env:VOLCENGINE_IMAGE_MODELS="doubao-seedream-5-0-lite-260128"
$env:VOLCENGINE_IMAGE_SIZE="1440x2560"
.\.venv\Scripts\python.exe -m apps.cli auto --title "每日新闻" --prompt "财经产业 / 公司政策 / 市场变化" --assets-glob "assets/empty/*" --login-hold 600
```

## 免费额度查询

GUI 的 `配置` 页提供两组额度查询按钮：

- `查询阿里云百炼额度`：调用 `apps.cli aliyun-quota`，读取阿里云百炼官方免费额度页。
- `查询火山引擎 Ark 额度`：调用 `apps.cli volcengine-quota`，读取火山引擎 Ark 官方用量/免费额度页。
- `Save raw snapshot`：默认开启，把原始可见文本、解析结果和错误列表写入 `data/quota/`，便于字段显示 `unknown` 时排查。

首次使用建议不要勾选 Headless，并把登录等待设为 `600` 秒，在弹出的浏览器里完成登录。登录态分别保存在：

```text
data/browser/aliyun-console-profile
data/browser/volcengine-console-profile
```

两项额度查询都不会调用模型推理 API，因此不会为了查询余额而消耗 token 或图片生成次数。当前解析规则、`status` 字段和 CLI 参数见 `docs/模型免费额度查询-2026-07-03.md`。

## 2026-07-03 火山 Seedream 实测

使用 `VOLCENGINE_API_KEY`、`VOLCENGINE_IMAGE_SIZE=1440x2560` 逐一调用 `src.images.volcengine_images.generate_volcengine_image`，验证以下模型均可通过当前项目封装正常生成并下载图片：

| 模型 | 状态 | 输出 |
|---|---|---|
| `doubao-seedream-5-0-lite-260128` | 成功 | `output/volcengine_seedream_verify_20260703_095446/doubao-seedream-5-0-lite-260128/ai_volcengine_20260703_015536.jpg` |
| `doubao-seedream-4-5-251128` | 成功 | `output/volcengine_seedream_verify_20260703_095446/doubao-seedream-4-5-251128/ai_volcengine_20260703_015623.jpg` |
| `doubao-seedream-4-0-250828` | 成功 | `output/volcengine_seedream_verify_20260703_095446/doubao-seedream-4-0-250828/ai_volcengine_20260703_015657.jpg` |

本次额外用 `System.Drawing.Image.FromFile` 校验了落盘图片，三张图片均为 `1440x2560`，不是空文件或错误响应内容。

## 注意事项

- GUI 只把供应商和模型选择注入当前子进程；不会修改 `docs/*api-key.md`。
- API key 是否有额度，最终仍以各供应商控制台账单/额度页为准；额度查询功能会读取官方控制台页面，真实生成测试仍会实际消耗少量模型额度。
- `wan2.7-image-pro` 支持更高规格，但通常更慢，也更容易消耗额度；批量发帖时建议先用 `wan2.7-image` 小规模验证。
- 若没有本地图片，`assets-glob` 可以指向空目录，例如 `assets/empty/*`，让系统自动配图。
