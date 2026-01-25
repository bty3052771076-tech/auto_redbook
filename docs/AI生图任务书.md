# AI 生图任务书（ChatGPT Images 配图）

## 1. 背景
当前工作流在“每日新闻”等场景下会在无用户图片素材时使用图片检索（如 Pexels）进行自动配图，但存在**图文不匹配**的情况，导致草稿质量不稳定。

你已购买 ChatGPT Plus，希望工作流在需要配图时进入 `https://chatgpt.com/images`，根据新闻内容自动撰写提示词并生成更贴合内容的图片，然后将图片下载到本地并作为草稿配图上传。

## 2. 可行性结论（先说结论）
**技术上可行，但不稳定且有风险。**

- 可行：可以用浏览器自动化（Playwright）驱动网页，在 `chatgpt.com/images` 输入提示词、触发生成、下载图片到本地，再喂给小红书发布页上传。
- 不稳定：ChatGPT 网页 UI 结构可能频繁变化、需要人工登录/验证码、且可能对自动化行为敏感；因此需要更强的“失败留证 + 选择器兜底 + 人工介入”机制。
- 成本/合规提醒：ChatGPT Plus 是网页订阅，不等同于 OpenAI API 的可编程额度；本方案属于**自动化操作网页**，与直接调用官方 API 是两条路径。后续若要稳定性更高，建议预留 “API 生图” 方案作为替代。

## 3. 目标与范围
### 3.1 目标
1) 当 `assets` 为空或图片不满足要求时，自动生成 1 张（或 N 张）与新闻内容强相关的配图。
2) 图片下载到本地工作区，并纳入 `data/posts/<post_id>/assets/` 的素材管理流程。
3) 不改变“只保存草稿、不点击发布”的原则。

### 3.2 不在本任务范围
- 不在本任务中直接改动现有代码（本文件仅定义需求与设计约束）。
- 不处理账号风控绕过/验证码破解。
- 不做多账号并发与任务调度优化（可作为后续增强）。

## 4. 现状观察（来自 MCP 页面探测）
使用 MCP 浏览器打开 `https://chatgpt.com/images` 时，未登录状态下页面包含：
- 顶部 banner：存在按钮 **“登录”**、**“免费注册”**（可作为“未登录”判定信号）。
- 主区域：存在 **“选择文件”** 按钮、以及大量“风格/示例提示词”按钮列表。

说明：上述探测是在“未登录/新 profile”的上下文中完成；要识别“输入框”和“生成图片区域”，需要在**你已登录 ChatGPT 的 Chrome profile**下再次探测并固化选择器（此任务后续实施阶段完成）。

## 5. 需求说明
### 5.1 输入
对每条待配图的 post（尤其是每日新闻）可用信息：
- `post.title`（可能为“每日新闻｜xxx”短标题）
- `post.body`（包含“新闻内容/我的点评”等结构化正文）
- `post.platform.news.picked`（如有：title/source/domain/description/content/url/publishedAt 等）
- 用户提示词（如有）：`prompt`

### 5.2 输出
- 下载得到的图片文件（推荐 `png` 或 `jpg`），保存到：
  - `data/posts/<post_id>/assets/ai_<timestamp>_<n>.png`
- 对应元数据（用于追踪/回放）：
  - `platform.image.provider="chatgpt_images"`
  - `platform.image.prompt`（实际用于生图的提示词）
  - `platform.image.generated_at`、`platform.image.variation`（如有）
  - 失败时写入 `platform.image.error`，并保存证据（HTML/截图）

### 5.3 生成提示词（Prompt）要求
提示词目标：**生成“新闻主题相关但不冒充真实照片/不捏造具体事实”的概念图/插画**，降低“图文不符”风险。

建议模板（示例，实施时由 LLM 生成）：
- 主题：用 1 句概括 picked 新闻核心主题（不写具体数字/人名细节，除非新闻信息明确且允许）。
- 画面元素：3~6 个与主题强绑定的视觉元素（场景、物体、符号）。
- 风格：建议统一风格（如“现代扁平插画 / 新闻插画 / 3D 渲染 / 电影感写实插画”择一），并明确“无文字、无水印、无 logo”。
- 构图：竖版 3:4 或 2:3（贴合小红书图文），主体居中，留白适中。
- 安全限制：不生成真实人物肖像、不含仇恨/暴力血腥/违法内容、不用受版权保护的角色/品牌标识。

### 5.4 执行流程（自动化）
1) 打开 `https://chatgpt.com/images`（使用持久化 profile）。
2) 检测登录态：
   - 若出现“登录”按钮：进入登录等待（人工扫码/验证），直到检测到输入框出现为止。
3) 输入提示词并触发生成：
   - 在输入框粘贴 prompt；触发方式可能为：点击“生成/创建”按钮或按 Enter（需以页面实际为准）。
4) 等待图片生成完成：
   - 以“图片卡片出现 + 可下载按钮出现/图片资源可访问”为完成信号。
5) 下载图片到本地：
   - 首选：读取图片元素的 `currentSrc` 并直接落盘原图字节（`http/https` 用带 cookie 的 request 下载；`blob/data` 用页面内 fetch 取回字节），避免 UI 截图截到“模糊/生成中”预览。
   - 备选：点击“下载”触发浏览器下载（Playwright `expect_download`）。
6) 验证文件：
   - 存在、大小 > 10KB、格式可读；失败则重试 1~2 次。
7) 回到小红书草稿保存流程：将该图片作为 `assets` 上传。

## 6. 浏览器与 Profile 设计（使用已登录的 Chrome Profile）
为减少“无法登录/反复登录”的问题，ChatGPT Images 生图建议**直接复用你当前已登录 ChatGPT 的 Chrome profile**，并使用系统 Chrome（而不是 Playwright 自带 Chromium）。

### 6.1 固定使用的 Chrome 可执行文件
- `C:\Program Files\Google\Chrome\Application\chrome.exe`

### 6.2 固定使用的 user-data-dir / profile-directory（你已登录 ChatGPT）
- `--user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile"`
- `--profile-directory="Default1"`

你可用下列命令验证该 profile 下已登录（PowerShell）：
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="D:\AI\codex\redbook_workflow\data\browser\chrome-profile" --profile-directory="Default1"
```

### 6.3 自动化实现约束（实施阶段）
- 生图模块启动浏览器时必须复用上述 profile（否则会变成未登录态，页面出现“登录/免费注册”）。
- 实现建议通过环境变量配置（便于切换/复用）：`CHATGPT_CHROME_EXECUTABLE` / `CHATGPT_CHROME_USER_DATA_DIR` / `CHATGPT_CHROME_PROFILE` / `CHATGPT_IMAGE_TIMEOUT_S`。
- 运行自动化前建议关闭所有 Chrome 窗口，避免 profile 被占用导致启动失败/数据未落盘。
- 若后续仍希望隔离 ChatGPT 与小红书站点，可在“同一个 user-data-dir”中使用不同 `--profile-directory` 分开管理登录态（但这会要求你分别登录一次）。
- 为降低 Cloudflare 反复触发概率，可选用“连接到已打开的 Chrome（CDP）”模式：
  - 你先用普通 Chrome 打开 `https://chatgpt.com/images` 并通过校验；
  - 启动 Chrome 时带 `--remote-debugging-port=9222`；
  - 自动化通过 `CHATGPT_CDP_URL=http://127.0.0.1:9222` 连接到现有窗口并复用页面（避免重新启动/重新导航带来的校验）。
  - 为保证“全流程自动化直到保存小红书草稿”，建议同时设置 `XHS_CDP_URL=http://127.0.0.1:9222` 让小红书自动化也复用同一个 Chrome（否则 profile 正在被占用时可能启动失败）。

## 7. 失败处理与降级策略
- 登录/验证码：自动化不尝试绕过；进入“等待人工处理”模式，并在超时后失败退出。
- Cloudflare 校验：可能出现 `cdn-cgi/challenge-platform` 校验页；自动化**不做绕过**，只会等待/留证。
  - 若校验页可正常展示：你可在弹出的 Chrome 窗口中手动完成校验后继续。
  - 若校验页长期白屏/加载中（常见于自动化被拦截）：建议启用“手动生图降级”，改为打开**普通 Chrome**（同一 profile）生成并下载图片到 `data/posts/<post_id>/assets/`，脚本检测到新图片后继续流程。
- UI 变更/选择器失效：自动保存证据（截图 + HTML + 控制台错误），便于快速修复。
- 生图失败/超时：重试 1 次；仍失败则降级到图片检索（Pexels）或要求用户提供图片。
- 下载失败：尝试点击其他变体图，或切换下载方式（下载按钮 vs 打开原图）。

## 8. 验收标准
1) 在“每日新闻”场景下，生成的图片与 picked 新闻主题一致（人工抽检通过率明显高于检索配图）。
2) 自动化稳定性：连续 5 次运行中，至少 4 次可在无需修改选择器的情况下完成“生成 + 下载”。
3) 落盘完整：每次生成都能在 `data/posts/<post_id>/assets/` 看到图片文件，并在 `platform.image` 记录 prompt/状态/错误。
4) 安全合规：提示词不包含敏感信息、不过度使用真实人物肖像/品牌标识，不生成带文字水印的图。

## 9. 测试计划（实施阶段）
- 探测测试（dry-run）：只打开 `chatgpt.com/images` 并输出关键元素是否存在（登录按钮/输入框/生成按钮/图片容器）。
- 端到端（单条）：`每日新闻 --count 1 --assets-glob empty/*` → AI 生图 → 小红书保存草稿。
- 端到端（多条）：`每日新闻 --count 3`，每条生成 1 张图并分别保存。

## 10. 里程碑与任务拆解（实施阶段）
1) 选择器固化：登录态下识别输入框、生成按钮、图片卡片与下载按钮。
2) Prompt 生成器：从 `platform.news.picked` 生成稳定 prompt（含风格与安全限制）。
3) 下载与落盘：实现下载、文件校验、元数据记录。
4) 与现有工作流对接：无图时优先 AI 生图；失败时回退检索配图。
5) 回归：验证小红书上传与草稿保存稳定性。
