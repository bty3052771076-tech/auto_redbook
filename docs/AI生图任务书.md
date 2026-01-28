# AI 生图任务书（阿里云百炼 / DashScope API 配图）

## 1. 背景
当前工作流在“每日新闻”等场景下，若用户未提供图片素材，会走图片检索（如 Pexels）自动配图。但检索配图经常出现**图文不匹配**，影响草稿质量。

为“省事稳定”，本任务将“网页式 GPT 生图（chatgpt.com/images + 浏览器自动化）”彻底移除，改为使用**阿里云百炼（DashScope）图像生成 API**：
- 由程序根据新闻内容自动拼接提示词（prompt）
- 直接调用 API 生图并下载落盘
- 再由小红书自动化上传并保存草稿

## 2. 可行性结论
**可行，且相对网页自动化更稳定。**

- 不依赖网页 UI / 选择器，不会被 Cloudflare 人机校验卡住
- 生图结果通过 URL 直接下载落盘，便于追溯与重试
- 失败可做“按超时/网络错误重试”，并在多次失败后放弃该条图片（不中断整体流程）

## 3. 目标与范围
### 3.1 目标
1) 当 `assets` 为空时，自动为每条草稿生成 1 张（或 N 张）与内容强相关的配图。
2) 图片保存到 `data/posts/<post_id>/assets/`，并写入 `post.platform.image / post.platform.images` 元数据。
3) 保持原则：**只保存草稿，不点击发布**。

### 3.2 非目标
- 不做复杂的“多风格/多分镜”创作（先保证稳定、可用）。
- 不做并发队列与调度优化（本任务先串行，避免限流/失败难排查）。
- 不做自动写入署名到正文（仅元数据保存）。

## 4. 输入与输出
### 4.1 输入
每条待配图的 post 可用信息：
- `post.title`
- `post.body`
- `post.topics`
- （每日新闻）`post.platform.news.picked.title/description/...` 已被写入正文与元数据
- 用户提示词（可选）：`prompt`

### 4.2 输出
- 图片文件：`data/posts/<post_id>/assets/ai_aliyun_<timestamp>.png|jpg|webp`
- 元数据（示例字段）：
  - `platform.image.provider="aliyun"`
  - `platform.image.model` / `size`
  - `platform.image.prompt`（用于生图的提示词；注意不含任何 API Key）
  - `platform.image.method="dashscope_url"` / `src_url`
  - `platform.image.attempt_max` / `attempt_errors`（如发生重试）

## 5. 提示词（Prompt）要求
提示词目标：生成“与主题强相关的新闻插画/封面图”，同时降低不合规与不可用输出：
- 竖版 3:4（适配小红书图文）
- **禁止文字/字幕/水印/logo/品牌标识**（避免被小红书或素材规则拦截）
- 不使用可识别真人肖像（用抽象符号或背影/剪影表达）
- 画面干净、构图简洁、适合资讯封面

## 6. 配置设计（本机保存，不提交仓库）
Key 配置（二选一）：
- 环境变量：`ALIYUN_IMAGE_API_KEY`（或 `DASHSCOPE_API_KEY`）
- 本机文件：`docs/aliyun_image_api-key.md`（参考 `docs/aliyun_image_api-key.example.md`；已被 `.gitignore` 忽略）

可选参数（环境变量）：
- `ALIYUN_IMAGE_MODEL`：默认 `qwen-image-plus`（可改 `qwen-image-max` 等）
- `ALIYUN_IMAGE_SIZE`：默认 `1104*1472`
- `ALIYUN_IMAGE_TIMEOUT_S`：默认 `180`
- `ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S`：默认 `60`
- `ALIYUN_IMAGE_MAX_ATTEMPTS`：默认 `3`
- `ALIYUN_IMAGE_RETRY_SLEEP_S`：默认 `2`
- `ALIYUN_IMAGE_CALL_MODE`：`auto` / `sync` / `async` / `text2image`（默认 `auto`）

支持模型（文生图，模型名以百炼控制台为准，均使用同一把 API Key）：
- Qwen-Image：`qwen-image-max` / `qwen-image-plus` / `qwen-image`
- Z-Image：`z-image-turbo`
- 通义万相：`wan2.6-t2i` / `wan2.5-t2i-preview` / `wanx2.1-t2i-turbo` 等

备注：文生图接口返回的是图片 URL（通常 24 小时有效），必须下载后才能保存为本地 PNG/JPG 用于上传。

## 7. 失败处理策略
- 单条图片生成超时/网络错误：自动重试，最多 `ALIYUN_IMAGE_MAX_ATTEMPTS` 次。
- 超过最大尝试次数：放弃该条图片，标记该条 post 的 `platform.image_generate.give_up=true`，并跳过该条（避免整体流程卡死）。
- 可选降级（后续增强）：放弃后回退到 `pexels` 检索配图或要求用户提供图片。

## 8. 验收标准
1) “每日新闻”无本地图片时，能稳定生成并落盘配图，随后保存小红书草稿成功。
2) 连续运行 3 次 `auto --count 3`，图片生成阶段不出现长时间卡死（超时应重试/放弃）。
3) `post.json` 中记录了可追溯图片元信息（不包含任何密钥）。

## 9. 测试计划
- 单元测试：重试/放弃逻辑（模拟超时/异常）。
- 端到端：`IMAGE_PROVIDER=aliyun` + `--assets-glob empty/pics/*` + `--count 3`，检查落盘文件存在、草稿保存成功。

## 10. 进度更新
- 2026-01-28：补充文生图模型清单（Qwen-Image / Z-Image / 通义万相）与 URL 下载注意事项，并同步 README。
